import json

import httpx
import pytest

from app.chat import ChatService, Decision, HandOff, rule_decision
from app.knowledge import (
    AnswerDraft,
    Citation,
    KnowledgeAgent,
    KnowledgeAnswer,
    KnowledgeBase,
    numbers,
    paragraphs,
    topic_query,
)
from app.models import Context

TU_DUC = (
    "Lăng Tự Đức là một quần thể kiến trúc ở Huế, nơi chôn cất vua Tự Đức. Lăng được xây từ năm 1864 đến 1867.\n\n"
    "Khung cảnh có hồ Lưu Khiêm, đảo Tịnh Khiêm và nhiều điện thờ.\n\n"
    "== Tham khảo ==\nLưu trữ ngày 18 tháng 5 năm 2006 tại Wayback Machine."
)


def wiki_transport(pages=None):
    """Fake MediaWiki API: search returns the given titles; extracts return their text."""
    pages = pages if pages is not None else {"Lăng Tự Đức": TU_DUC}
    calls = []

    def handler(request):
        params = dict(request.url.params)
        calls.append((request.url.host, params))
        if params.get("list") == "search":
            hits = [{"title": t} for t in pages if request.url.host.startswith("vi.")]
            return httpx.Response(200, json={"query": {"search": hits}})
        title = params["titles"]
        return httpx.Response(200, json={"query": {"pages": [{
            "title": title, "extract": pages[title], "fullurl": f"https://vi.wikipedia.org/wiki/{title}",
        }]}})

    return httpx.MockTransport(handler), calls


# --- Retrieval ----------------------------------------------------------------------------


def test_numbers_ignore_separators_and_single_digits():
    assert numbers("Vé 150.000 ₫, trẻ 7 tuổi, mở 7:30, năm 1864") == {"150000", "730", "1864"}


def test_paragraphs_drop_reference_sections_and_cap_length():
    parts = paragraphs(TU_DUC + "\n\n" + "Câu dài. " * 200)
    assert not any("Wayback" in p for p in parts)
    assert all(len(p) <= 700 for p in paragraphs("Một câu. " * 300))


def test_topic_query_strips_question_words_only():
    assert topic_query("Lăng Tự Đức có gì đặc biệt, giá vé bao nhiêu?") == "Lăng Tự Đức"
    assert topic_query("Đà Lạt có gì đặc biệt?") == "Đà Lạt"
    assert topic_query("Chợ Đông Ba mở cửa mấy giờ ạ?") == "Chợ Đông Ba"


async def test_wikipedia_passages_are_ranked_and_cited():
    transport, calls = wiki_transport()
    found = await KnowledgeBase(transport=transport).search("Lăng Tự Đức", "wikipedia", "Huế")
    assert found and found[0][0] == "Lăng Tự Đức" and "1864" in found[0][2]
    assert found[0][1].startswith("https://vi.wikipedia.org/")
    assert not any(c[0].startswith("en.") for c in calls)  # Vietnamese article found, no English fallback


async def test_off_topic_pages_are_filtered():
    transport, _ = wiki_transport({"Biệt đội siêu anh hùng": "Một đặc vụ của S.H.I.E.L.D trong phim Marvel."})
    assert await KnowledgeBase(transport=transport).search("Lăng Tự Đức", "wikipedia") == []


async def test_network_errors_return_no_passages():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    assert await KnowledgeBase(transport=transport).search("Huế", "wikivoyage") == []


@pytest.mark.parametrize("query,destination,expected", [
    ("vé lăng Tự Đức", "Huế", ["Vé lăng Tự Đức"]),
    ("vé Phố cổ Hội An", "Huế", ["Vé tham quan phố cổ Hội An"]),
    ("Đà Lạt", "Huế", []),
])
async def test_ticket_table_matches_the_asked_sight_or_city(query, destination, expected):
    found = await KnowledgeBase().search(query, "tickets", destination)
    titles = [t for t, *_ in found]
    assert len(titles) == len(expected) and all(t.startswith(e) for t, e in zip(titles, expected, strict=True))


async def test_city_fee_question_lists_that_city():
    found = await KnowledgeBase().search("giá vé tham quan Huế", "tickets")
    assert len(found) >= 3 and all("Hội An" not in t for t, *_ in found)


# --- Submit gate ---------------------------------------------------------------------------


def test_answer_must_cite_unless_not_found():
    with pytest.raises(ValueError, match="cite"):
        AnswerDraft(status="answered", text="Có.")
    assert AnswerDraft(status="not_found", text="Không thấy.").citations == []


class FakeBase:
    def __init__(self):
        self.queries = []

    async def search(self, query, source, destination=None):
        self.queries.append((query, source))
        if source == "tickets":
            return [("Vé lăng Tự Đức", "https://tuoitre.vn/x", "Vé lăng Tự Đức: 150.000 ₫/người lớn.", "tickets")]
        return [("Lăng Tự Đức", "https://vi.wikipedia.org/wiki/L", "Lăng xây từ năm 1864 đến 1867.", "wikipedia")]


def scripted(*answers, searches=(("Lăng Tự Đức", "tickets"), ("Lăng Tự Đức", "wikipedia"))):
    calls = [{"name": "search_knowledge", "args": {"query": q, "source": s}} for q, s in searches]
    calls += [{"name": "submit_answer", "args": {"answer_json": json.dumps(a)}} for a in answers]
    return calls


INVENTED = {"status": "answered", "text": "Vé 150.000 ₫, mở cửa 7:30.", "citations": ["t1", "x9"]}
GROUNDED = {"status": "partial", "text": "Vé 150.000 ₫, xây từ 1864. Nguồn không có giờ mở cửa.",
            "citations": ["t1", "w2"]}


async def test_gate_rejects_unknown_citations_and_invented_numbers_on_adk():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    model = ScriptedModel(calls=scripted(INVENTED, GROUNDED))
    answer = await KnowledgeAgent(FakeBase(), lambda: model, "adk").ask("Lăng Tự Đức?", Context())
    rejected = [o for o in model.observations if o.get("accepted") is False]
    assert rejected and any("x9" in e for e in rejected[0]["errors"]) and any("730" in e for e in rejected[0]["errors"])
    assert answer.status == "partial" and [c.id for c in answer.citations] == ["t1", "w2"]
    assert answer.citations[0].url == "https://tuoitre.vn/x"


async def test_gate_works_on_maf():
    pytest.importorskip("agent_framework")
    from test_maf_tools import ScriptedClient

    client = ScriptedClient(scripted(INVENTED, GROUNDED))
    answer = await KnowledgeAgent(FakeBase(), lambda: client, "maf").ask("Lăng Tự Đức?", Context())
    assert answer.answered_by == "llm" and answer.searches == ["tickets:lang tu duc", "wikipedia:lang tu duc"]


async def test_repeated_search_is_refused_and_budget_falls_back_to_quotes():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    searches = [("Huế", "wikipedia"), ("Huế", "wikipedia"), ("Huế 2", "wikivoyage"), ("Huế 3", "tickets"),
                ("Huế 4", "wikipedia"), ("Huế 5", "wikipedia")]
    model = ScriptedModel(calls=scripted(searches=searches))
    base = FakeBase()
    answer = await KnowledgeAgent(base, lambda: model, "adk", max_llm_calls=8).ask("Huế?", Context())
    assert len(base.queries) == 4  # the repeat and over-budget calls never reach the sources
    assert any("Already searched" in str(o) for o in model.observations)
    assert any("budget used up" in str(o) for o in model.observations)
    assert answer.answered_by == "extractive" and answer.citations


async def test_without_llm_quotes_the_best_passages():
    base = FakeBase()
    answer = await KnowledgeAgent(base).ask("Lăng Tự Đức có gì đặc biệt?", Context())
    assert base.queries == [("Lăng Tự Đức", "tickets"), ("Lăng Tự Đức", "wikipedia")]
    assert answer.answered_by == "extractive" and len(answer.citations) == 2


# --- Chat hand-off -------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Lăng Tự Đức có gì đặc biệt?", "giá vé Đại Nội", "Chùa Cầu mở cửa mấy giờ"])
def test_rule_router_sends_place_questions_to_the_guide(text):
    from app.chat import ChatSession

    assert rule_decision(ChatSession(), text).hand_off.agent == "guide_advisor"


class FakeGuide:
    def __init__(self):
        self.asked = []

    async def ask(self, question, context, destination=None):
        self.asked.append((question, destination))
        return KnowledgeAnswer(status="answered", text="Lăng xây từ 1864.", citations=[
            Citation(id="w1", source="wikipedia", title="Lăng Tự Đức", url="https://vi.wikipedia.org/wiki/L")])


class FixedConcierge:
    def __init__(self, decision):
        self.decision = decision

    async def decide(self, session, context):
        return self.decision


async def test_guide_gets_the_standalone_question_and_returns_citations():
    from test_chat import Orchestrator, Provider

    guide = FakeGuide()
    concierge = FixedConcierge(Decision(action="hand_off", hand_off=HandOff(
        agent="guide_advisor", reason="Hỏi về địa danh.", question="Lăng Tự Đức có gì đặc biệt?")))
    _, reply = await ChatService(Orchestrator(), Provider(), concierge, guide=guide).handle(None, "ở đó có gì?")
    assert guide.asked == [("Lăng Tự Đức có gì đặc biệt?", None)]
    assert reply.agent == "guide_advisor" and reply.citations[0].id == "w1"


async def test_model_outage_falls_back_to_quotes():
    def broken_model():
        raise RuntimeError("429 quota")

    base = FakeBase()
    answer = await KnowledgeAgent(base, broken_model, "adk").ask("Lăng Tự Đức có gì đặc biệt?", Context())
    assert answer.answered_by == "extractive" and answer.citations
