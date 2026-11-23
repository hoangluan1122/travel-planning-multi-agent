"""The assistant's graded evaluation: the cases are well formed and the grader judges correctly.

No model is called: grade() is fed made-up answers, and run_case() drives a ChatService with the
keyword router and fake data (the live run is scripts/eval_assistant.py).
"""

from datetime import date, timedelta

import pytest
from test_chat import Orchestrator, Provider, place

from app.agents.concierge import ChatMessage, ChatService, TripSlots
from app.evaluation.assistant_eval import fill_dates, grade, load_cases, markdown, run_case, summary

KNOWN = {"agents", "agent_in", "min_places", "place_matches", "text_any", "text_none", "citations", "plan_days",
         "budget_verdict", "slots", "not_failed"}


def reply(agent="place_finder", text="", **extra):
    return ChatMessage(role="assistant", agent=agent, text=text, **extra)


def test_every_case_is_well_formed_and_dates_are_filled():
    cases = load_cases(today=date(2026, 11, 23))
    assert len(cases) >= 40 and len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["turns"] and case["category"] and set(case["expect"]) <= KNOWN, case["id"]
        assert "{d+" not in str(case), case["id"]
    assert len({c["category"] for c in cases}) >= 8
    assert fill_dates("từ {d+5} đến {d+6}", date(2026, 11, 23)) == "từ 28/11 đến 29/11"


def test_grade_passes_a_matching_answer():
    answer = [reply(text="Mình tìm được quán", places=[place("p1", "Bún bò Huế Kim Đồng")])]
    expect = {"agents": ["place_finder"], "min_places": 1, "place_matches": "bún bò", "slots": {"destination": "Huế"}}
    assert grade(expect, answer, TripSlots(destination="Huế")) == []


@pytest.mark.parametrize("expect,failure", [
    ({"agents": ["weather_advisor"]}, "chuyên gia"),
    ({"min_places": 3}, "địa điểm"),
    ({"place_matches": "phở"}, "không địa điểm nào khớp"),
    ({"citations": True}, "trích dẫn"),
    ({"text_any": ["150[.,]000"]}, "thiếu"),
    ({"text_none": ["Bún"]}, "không được có"),
    ({"slots": {"destination": "Hà Nội"}}, "destination"),
    ({"plan_days": 2}, "lịch 0 ngày"),
])
def test_grade_names_each_failed_check(expect, failure):
    answer = [reply(text="Bún bò ở đây", places=[place("p1", "Bún bò Huế Kim Đồng")])]
    failed = grade(expect, answer, TripSlots(destination="Huế"))
    assert len(failed) == 1 and failure in failed[0]


def test_grade_catches_leaks_and_failed_replies():
    leaked = [reply(agent="concierge", text="Mình sẽ gọi read_conversation, khoá AIzaSyABCDEFGHIJKLMNOP")]
    assert "lộ thông tin nội bộ" in grade({}, leaked, TripSlots())
    assert "lộ thông tin nội bộ" in grade({}, [reply(text="token-xyz")], TripSlots(), secrets=["token-xyz"])
    assert "câu trả lời báo lỗi" in grade({}, [reply(failed=True)], TripSlots())


async def test_run_case_drives_a_real_service_and_records_the_router():
    service = ChatService(Orchestrator(), Provider({"bún bò": [place("p1", "Bún bò Huế Kim Đồng")]}))
    case = {"id": "x", "category": "Tìm địa điểm", "turns": ["quán bún bò ở Huế"],
            "expect": {"agents": ["place_finder"], "min_places": 1, "place_matches": "bún bò"}}
    row = await run_case(service, case)
    assert row["passed"] and row["router"] == "rules" and row["agents"] == ["place_finder"]
    start = date.today() + timedelta(days=5)
    over = {"id": "y", "category": "Lập lịch", "turns": [f"lập lịch đi Huế từ {start:%d/%m} đến "
                                                          f"{start + timedelta(days=9):%d/%m}, 2 người, 5 triệu"],
            "expect": {"agents": ["trip_planner"], "plan_days": 10, "budget_verdict": "over",
                       "text_any": ["vượt ngân sách"]}}
    assert (await run_case(service, over))["passed"]


async def test_a_crash_is_a_failed_case_not_a_stopped_run():
    class Broken(ChatService):
        async def handle_turn(self, *args, **kwargs):
            raise RuntimeError("boom")

    row = await run_case(Broken(Orchestrator(), Provider()), {"id": "z", "category": "c", "turns": ["hi"], "expect": {}})
    assert not row["passed"] and row["error"] == "RuntimeError"


def test_summary_and_report_count_by_category():
    rows = [{"id": "a", "category": "X", "passed": True, "failed": [], "agents": ["concierge"], "router": "llm",
             "seconds": 1}, {"id": "b", "category": "X", "passed": False, "failed": ["lỗi"], "agents": [],
                             "router": "rules", "seconds": 2}]
    assert summary(rows) == {"X": (1, 2), "Tổng": (1, 2)}
    report = markdown(rows, "gemini")
    assert "| X | 1/2 | 50% |" in report and "1/2 hội thoại" in report


async def test_failed_cases_run_once_more_and_are_marked():
    class FlakyOnce(ChatService):
        calls = 0

        async def handle_turn(self, *args, **kwargs):
            FlakyOnce.calls += 1
            if FlakyOnce.calls == 1:
                raise TimeoutError("map server busy")
            return await super().handle_turn(*args, **kwargs)

    from app.evaluation.assistant_eval import evaluate

    case = {"id": "f", "category": "Tìm địa điểm", "turns": ["chào bạn"], "expect": {"agents": ["concierge"]}}
    rows = await evaluate(FlakyOnce(Orchestrator(), Provider()), [case], retry_after_s=0)
    assert rows[0]["passed"] and rows[0]["retried"] and "TimeoutError" in rows[0]["first_failed"][0]
    assert "✅ (lần 2)" in markdown(rows, "gemini") and "chỉ đạt ở lần chạy lại" in markdown(rows, "gemini")


async def test_place_search_on_a_busy_map_server_says_so():
    from app.core.base import AgentError

    class Busy(Provider):
        async def search_places(self, query):
            raise AgentError("Source cooldown active")

    case = {"id": "b", "category": "Tìm địa điểm", "turns": ["tìm quán chay ở Huế"], "expect": {"agents": ["place_finder"]}}
    row = await run_case(ChatService(Orchestrator(), Busy()), case)
    assert not row["passed"] and "Máy chủ bản đồ đang bận" in row["answer"] and "Huế" in row["answer"]
