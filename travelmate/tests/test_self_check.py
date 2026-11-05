"""Metacognition: rule-based self-check of a draft, then LLM revision with feedback."""

from datetime import date, timedelta

import pytest
from test_planning import payload

from app.agents import (
    BudgetAgent,
    MemoryAgent,
    PlaceAgent,
    PlannerAgent,
    RecommendationAgent,
    Registry,
    WeatherAgent,
)
from app.models import (
    Activity,
    Day,
    Draft,
    Place,
    PlaceResult,
    TravelPlan,
    TripRequest,
    WeatherDay,
    WeatherResult,
)
from app.planning import PlanningOrchestrator
from app.providers import DemoProvider
from app.self_check import feedback_from, review_draft

D1 = date.today() + timedelta(days=2)
D2 = D1 + timedelta(days=1)


def place(ident, name, kind):
    return Place(id=ident, name=name, address="a", latitude=16.4, longitude=107.6, source="t", types=[kind])


PLACES = PlaceResult(places=[
    place("m", "Bảo tàng", "museum"), place("p1", "Công viên A", "park"), place("p2", "Công viên B", "park"),
    place("r", "Quán Cơm", "restaurant"), place("v", "Quán Chay", "restaurant"), place("t", "Lăng Tự Đức", "tomb"),
    place("g", "Phòng tranh", "gallery"), place("p3", "Công viên C", "park"),  # p3 stays unused
])


def act(pid, start, end):
    return Activity(place_id=pid, start_minute=start, end_minute=end)


def ids(checks, passed):
    return {c.id for c in checks if c.passed is passed}


def test_good_draft_passes_every_check():
    draft = Draft(days=[
        Day(date=D1, activities=[act("m", 540, 660), act("v", 690, 780), act("t", 840, 960)]),
        Day(date=D2, activities=[act("g", 540, 660), act("r", 690, 780), act("p1", 840, 900)]),
    ])
    weather = WeatherResult(days=[WeatherDay(date=D1, weather_code=63)])
    checks = review_draft(draft, PLACES, weather, [("“chay”", "chay", {"v"})])
    assert ids(checks, False) == set() and {"wish:chay", "meals", "rain", "repeats"} <= ids(checks, True)


def test_failures_are_specific_and_become_feedback():
    draft = Draft(days=[
        Day(date=D1, activities=[act("p1", 540, 660), act("p2", 690, 780), act("m", 840, 960)]),
        Day(date=D2, activities=[act("m", 540, 660), act("p1", 690, 800)]),
    ])
    weather = WeatherResult(days=[WeatherDay(date=D1, weather_code=81)])
    checks = review_draft(draft, PLACES, weather, [("“chay”", "chay", {"v"}), ("“lăng”", "lăng", {"t"})])
    assert ids(checks, False) == {"wish:chay", "wish:lang", "meals", "rain", "repeats"}
    feedback = feedback_from(checks)
    assert any("chay" in f for f in feedback) and any(D1.isoformat() in f for f in feedback)


def test_checks_never_demand_the_impossible():
    only_sights = PlaceResult(places=[place("p1", "Công viên A", "park"), place("p2", "Công viên B", "park")])
    draft = Draft(days=[Day(date=D1, activities=[act("p1", 540, 700), act("p2", 720, 900)])])
    rainy = WeatherResult(days=[WeatherDay(date=D1, weather_code=63)])
    # no meal candidates, no indoor alternative, single day, wish without candidates: nothing applies
    assert review_draft(draft, only_sights, rainy, [("“chay”", "chay", set())]) == []


# --- revision loop in the orchestrator --------------------------------------------------


class ScriptedLLM:
    """Stands in for the itinerary LLM: returns drafts in order and records the feedback seen."""

    def __init__(self, drafts):
        self.drafts, self.feedback = list(drafts), []

    async def plan(self, data, context):
        self.feedback.append(list(data.feedback))
        return self.drafts.pop(0)(data)


def draft_with(*day_ids):
    def build(data):
        start = data.trip.start_date
        return Draft(days=[
            Day(date=start + timedelta(days=i), activities=[act(pid, 540 + j * 120, 640 + j * 120)
                                                            for j, pid in enumerate(pids)])
            for i, pids in enumerate(day_ids)
        ])
    return build


class Provider(DemoProvider):
    async def search(self, trip):
        return PlaceResult(places=[place("m", "Bảo tàng", "museum"), place("r", "Quán Cơm", "restaurant")])

    async def search_places(self, query):
        return PlaceResult(places=[place("v", "Quán Chay", "restaurant")])


class OnePlan:
    async def plan(self, trip, context, previous=None, observations=()):
        from test_planning_pattern import plan_dict

        return TravelPlan.model_validate(plan_dict([("restaurant", "chay")]))


def orchestrator(llm):
    registry = Registry()
    provider = Provider()
    for agent in [MemoryAgent(), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(llm), BudgetAgent()]:
        registry.register(agent)
    return PlanningOrchestrator(registry, provider, OnePlan())


@pytest.mark.asyncio
async def test_failed_check_is_fed_back_and_the_fixed_draft_is_kept():
    llm = ScriptedLLM([draft_with(["m", "r"], ["r", "m"]), draft_with(["m", "v"], ["r", "m"])])
    result = await orchestrator(llm).plan(TripRequest(**payload()))
    report = result.self_check
    assert llm.feedback[0] == [] and any("chay" in f for f in llm.feedback[1])
    assert report.revisions == 1 and report.chosen_round == 2 and report.final_passed
    assert any(a.place_id == "v" for d in result.draft.days for a in d.activities)


@pytest.mark.asyncio
async def test_a_worse_revision_does_not_replace_a_better_draft():
    bad = draft_with(["m", "r"], ["r", "m"])
    llm = ScriptedLLM([bad, bad, bad])
    result = await orchestrator(llm).plan(TripRequest(**payload()))
    assert result.self_check.revisions == 2 and result.self_check.chosen_round == 1
    assert not result.self_check.final_passed


@pytest.mark.asyncio
async def test_invalid_revision_is_discarded():
    def invented(data):
        return Draft(days=[Day(date=data.trip.start_date, activities=[act("nowhere", 540, 600)]),
                           Day(date=data.trip.end_date, activities=[act("m", 540, 600)])])

    llm = ScriptedLLM([draft_with(["m", "r"], ["r", "m"]), invented])
    result = await orchestrator(llm).plan(TripRequest(**payload()))
    assert result.self_check.chosen_round == 1 and len(result.self_check.rounds) == 1


@pytest.mark.asyncio
async def test_demo_planner_reports_checks_without_revising():
    registry = Registry()
    provider = Provider()
    for agent in [MemoryAgent(), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(), BudgetAgent()]:
        registry.register(agent)
    result = await PlanningOrchestrator(registry, provider, OnePlan()).plan(TripRequest(**payload()))
    assert result.self_check.revisions == 0 and result.self_check.rounds


def test_feedback_names_what_to_keep_and_wishes_outrank_other_failures():
    from app.models import CheckResult
    from app.self_check import draft_score

    def c(ident, passed):
        return CheckResult(id=ident, label=ident, passed=passed, detail=f"{ident} detail")

    misses_wish = [c("wish:lang", False), c("meals", True), c("repeats", True)]
    two_minor = [c("wish:lang", True), c("meals", False), c("repeats", False)]
    assert draft_score(two_minor) < draft_score(misses_wish)  # the user's stated wish comes first
    feedback = feedback_from(misses_wish)
    assert feedback[0].startswith("Cần sửa") and "meals" in feedback[-1] and "repeats" in feedback[-1]


@pytest.mark.asyncio
async def test_a_revision_that_errors_keeps_the_best_draft():
    class Quota(Exception):
        code = 429

    def quota(data):
        raise Quota("rate limited")

    llm = ScriptedLLM([draft_with(["m", "r"], ["r", "m"]), quota])
    result = await orchestrator(llm).plan(TripRequest(**payload()))
    assert result.self_check.chosen_round == 1 and result.draft.days
