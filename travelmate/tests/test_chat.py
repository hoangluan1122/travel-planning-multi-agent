import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.agents.concierge import (
    ChatService,
    ChatSession,
    ConciergeAgent,
    Decision,
    HandOff,
    PlaceQuery,
    SessionStore,
    TripSlots,
    extract_slots,
    rule_decision,
)
from app.core.base import AgentError
from app.core.models import Place, PlaceResult, WeatherDay, WeatherResult
from app.main import Settings, create_app
from app.tools.places.providers import DemoProvider


def place(ident, name):
    return Place(id=ident, name=name, address="a", latitude=16.4, longitude=107.5, source="t", types=["restaurant"])


class Provider(DemoProvider):
    def __init__(self, found=None):
        self.found = found or {}
        self.queries = []

    async def search_places(self, query):
        self.queries.append((query.destination, query.category, query.keyword))
        return PlaceResult(places=self.found.get(query.keyword, []))

    async def forecast(self, trip):
        return WeatherResult(days=[WeatherDay(date=trip.start_date, weather_code=61)])


class Orchestrator:
    def __init__(self):
        self.trips = []

    async def plan(self, trip):
        self.trips.append(trip)
        app = create_app(Settings(_env_file=None))  # demo pipeline gives a real PlanResponse
        response = TestClient(app).post("/api/v1/plans/preview", json=trip.model_dump(mode="json"))
        from app.core.models import PlanResponse

        return PlanResponse.model_validate(response.json())


class FixedConcierge:
    def __init__(self, *decisions):
        self.decisions = list(decisions)

    async def decide(self, session, context):
        item = self.decisions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def soon(days):
    return date.today() + timedelta(days=days)


# --- Hand-off schema (submit gate) -------------------------------------------------------


def test_decision_gate_rejects_incomplete_hand_offs():
    with pytest.raises(ValueError, match="needs text"):
        Decision(action="reply", text=" ")
    with pytest.raises(ValueError, match="hand_off details"):
        Decision(action="hand_off")
    with pytest.raises(ValueError, match="place_query"):
        Decision(action="hand_off", hand_off=HandOff(agent="place_finder", reason="tìm quán"))
    with pytest.raises(ValueError):
        Decision.model_validate({"action": "hand_off", "hand_off": {"agent": "hacker", "reason": "x y z"}})


def test_slots_merge_keeps_known_details():
    known = TripSlots(destination="Huế", travelers=2)
    merged = known.merged(TripSlots(budget_vnd=Decimal(5_000_000)))
    assert (merged.destination, merged.travelers, merged.budget_vnd) == ("Huế", 2, Decimal(5_000_000))
    assert known.merged(TripSlots(destination="Hội An")).destination == "Hội An"


# --- Keyword router used without an LLM --------------------------------------------------


def test_extract_slots_reads_vietnamese_trip_details():
    start = soon(10)
    slots = extract_slots(f"Lên lịch đi Huế từ {start:%d/%m} đến {start + timedelta(days=1):%d/%m}, 2 người, 5 triệu")
    assert slots.destination == "Huế"
    assert (slots.start_date, slots.end_date) == (start, start + timedelta(days=1))
    assert slots.travelers == 2 and slots.budget_vnd == Decimal(5_000_000)
    three = extract_slots(f"đi Hội An {start.isoformat()} 3 ngày")
    assert three.destination == "Hội An" and three.end_date == start + timedelta(days=2)
    assert extract_slots("xin chào") == TripSlots()


@pytest.mark.parametrize("text,agent", [
    ("thời tiết Huế thế nào", "weather_advisor"),
    ("chi phí bao nhiêu", "budget_advisor"),
    ("lên lịch trình đi Huế", "trip_planner"),
    ("tìm quán chay ở Huế", "place_finder"),
])
def test_rule_router_picks_a_specialist(text, agent):
    decision = rule_decision(ChatSession(), text)
    assert decision.hand_off.agent == agent


def test_rule_router_continues_with_the_active_specialist():
    session = ChatSession()
    assert rule_decision(session, "xin chào").action == "reply"
    session.active_agent = "trip_planner"
    decision = rule_decision(session, "2 người, 5 triệu")
    assert decision.hand_off.agent == "trip_planner" and decision.hand_off.slots.travelers == 2


def test_rule_router_builds_a_food_query():
    query = rule_decision(ChatSession(), "tìm quán chay ở Huế").hand_off.place_query
    assert (query.category, query.keyword) == ("restaurant", "chay")


# --- Specialists through the service -----------------------------------------------------


async def test_trip_planner_collects_details_across_turns():
    orchestrator = Orchestrator()
    service = ChatService(orchestrator, Provider())
    session, reply = await service.handle(None, "lên lịch trình đi Huế")
    assert reply.agent == "trip_planner" and "ngày đi" in reply.text and "điểm đến Huế" in reply.text
    start = soon(5)
    session, reply = await service.handle(session.id, f"từ {start:%d/%m} đến {start + timedelta(days=1):%d/%m}, 2 người, 5 triệu")
    assert reply.plan is not None and reply.trip.destination == "Huế"
    assert orchestrator.trips[0].travelers == 2 and len(reply.plan.draft.days) == 2
    _, reply = await service.handle(session.id, "chi phí bao nhiêu")
    assert reply.agent == "budget_advisor" and "tổng ước tính" in reply.text and "Mức vừa phải" in reply.text
    # "What if" questions recompute without changing the plan.
    _, tried = await service.handle(session.id, "nếu ở khách sạn 1,5 triệu/đêm thì sao")
    assert tried.agent == "budget_advisor" and tried.text.startswith("Nếu ở 1.500.000 ₫/phòng/đêm")
    assert "tính thử" in tried.text and session.slots.budget_vnd == 5_000_000
    _, tried = await service.handle(session.id, "nếu đi 4 người, mức tiết kiệm thì có đủ không")
    assert "đi 4 người" in tried.text and "mức tiết kiệm" in tried.text


async def test_place_finder_widens_an_empty_keyword_search():
    provider = Provider({"": [place("p1", "Quán Bún")]})
    service = ChatService(Orchestrator(), provider)
    _, reply = await service.handle(None, "tìm quán chay ở Huế")
    assert provider.queries == [("Huế", "restaurant", "chay"), ("Huế", "restaurant", "vegetarian"),
                                ("Huế", "restaurant", "")]
    assert [p.name for p in reply.places] == ["Quán Bún"] and "tìm rộng hơn" in reply.text


async def test_place_finder_tries_the_english_tag_before_widening():
    provider = Provider({"vegetarian": [place("p1", "Quán Chay Liên Hoa")]})
    _, reply = await ChatService(Orchestrator(), provider).handle(None, "tìm quán chay ở Huế")
    assert reply.places[0].name == "Quán Chay Liên Hoa" and "tìm rộng hơn" not in reply.text


async def test_place_finder_asks_for_a_destination():
    _, reply = await ChatService(Orchestrator(), Provider()).handle(None, "tìm quán ăn ngon")
    assert reply.agent == "place_finder" and "thành phố nào" in reply.text


async def test_weather_advisor_uses_known_destination():
    service = ChatService(Orchestrator(), Provider())
    session, _ = await service.handle(None, "tìm quán chay ở Huế")
    _, reply = await service.handle(session.id, "thời tiết thế nào")
    assert reply.agent == "weather_advisor" and "Huế" in reply.text and "mưa" in reply.text


async def test_budget_advisor_needs_a_plan_first():
    _, reply = await ChatService(Orchestrator(), Provider()).handle(None, "chi phí bao nhiêu")
    assert "lịch trình" in reply.text and reply.plan is None


async def test_llm_decision_is_used_and_reason_is_shown():
    concierge = FixedConcierge(Decision(action="hand_off", hand_off=HandOff(
        agent="place_finder", reason="Người dùng muốn tìm quán ăn.",
        slots=TripSlots(destination="Huế"), place_query=PlaceQuery(category="restaurant", keyword="vegetarian"),
    )))
    provider = Provider({"vegetarian": [place("p1", "Quán Chay")]})
    _, reply = await ChatService(Orchestrator(), provider, concierge).handle(None, "có chỗ ăn chay không")
    assert reply.reason == "Người dùng muốn tìm quán ăn." and reply.places[0].name == "Quán Chay"


async def test_concierge_failure_falls_back_to_rules():
    concierge = FixedConcierge(AgentError("bad"))
    _, reply = await ChatService(Orchestrator(), Provider(), concierge).handle(None, "thời tiết ở Huế")
    assert reply.agent == "weather_advisor"


async def test_specialist_failure_becomes_a_reply():
    class Broken(Provider):
        async def search_places(self, query):
            raise AgentError("source down")

    _, reply = await ChatService(Orchestrator(), Broken()).handle(None, "tìm quán ở Huế")
    assert reply.agent == "place_finder" and "thử lại" in reply.text


def test_session_store_expires_and_caps(monkeypatch):
    store = SessionStore()
    first = store.get(None)
    assert store.get(first.id) is first
    first.touched -= 3 * 3600
    assert store.get(first.id) is not first


# --- Concierge LLM on both engines --------------------------------------------------------


def concierge_calls():
    good = {"action": "hand_off", "hand_off": {
        "agent": "place_finder", "reason": "Tìm quán ăn.", "slots": {"destination": "Huế"},
        "place_query": {"category": "restaurant", "keyword": "chay", "destination": "Huế"},
    }}
    bad = {"action": "hand_off", "hand_off": {"agent": "place_finder", "reason": "Tìm quán ăn."}}
    return [
        {"name": "read_conversation", "args": {}},
        {"name": "decide", "args": {"decision_json": json.dumps(bad)}},
        {"name": "decide", "args": {"decision_json": json.dumps(good)}},
    ]


def _session():
    session = ChatSession()
    from app.agents.concierge import ChatMessage

    session.messages.append(ChatMessage(role="user", text="tìm quán chay ở Huế"))
    return session


async def test_concierge_repairs_a_rejected_decision_on_adk():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    from app.core.models import Context

    model = ScriptedModel(calls=concierge_calls())
    decision = await ConciergeAgent(lambda: model, engine="adk").decide(_session(), Context())
    assert decision.hand_off.place_query.keyword == "chay"
    assert any(o.get("accepted") is False for o in model.observations)


async def test_concierge_repairs_a_rejected_decision_on_maf():
    pytest.importorskip("agent_framework")
    from test_maf_tools import ScriptedClient

    from app.core.models import Context

    client = ScriptedClient(concierge_calls())
    decision = await ConciergeAgent(lambda: client, engine="maf").decide(_session(), Context())
    assert decision.hand_off.agent == "place_finder" and client.index == 3


# --- HTTP endpoint ------------------------------------------------------------------------


def test_chat_endpoint_keeps_the_session_and_requires_the_token():
    settings = Settings(_env_file=None, travelmate_api_token="secret")
    client = TestClient(create_app(settings))
    assert client.post("/api/v1/chat", json={"message": "xin chào"}).status_code == 401
    auth = {"Authorization": "Bearer secret"}
    first = client.post("/api/v1/chat", json={"message": "tìm quán chay ở Huế"}, headers=auth).json()
    assert first["reply"]["agent"] == "place_finder" and first["active_agent"] == "place_finder"
    second = client.post("/api/v1/chat", json={"session_id": first["session_id"], "message": "lên lịch trình"},
                         headers=auth).json()
    assert second["session_id"] == first["session_id"] and "điểm đến Huế" in second["reply"]["text"]
    assert client.post("/api/v1/chat", json={"message": ""}, headers=auth).status_code == 422


def test_rule_router_splits_compound_questions_and_orders_them():
    decision = rule_decision(ChatSession(), "thời tiết Huế thế nào và lên lịch trình 2 ngày")
    assert [h.agent for h in decision.hand_offs()] == ["trip_planner", "weather_advisor"]
    single = rule_decision(ChatSession(), "tìm quán ăn và quán cà phê ở Huế")
    assert single.also == [] and single.hand_off.agent == "place_finder"


def test_decision_also_is_validated():
    with pytest.raises(ValueError, match="place_query"):
        Decision(action="hand_off", hand_off=HandOff(agent="weather_advisor", reason="thời tiết"),
                 also=[HandOff(agent="place_finder", reason="tìm quán")])
