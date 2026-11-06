from datetime import date, timedelta

import pytest

from app.agents.budget import BudgetAgent
from app.agents.itinerary import PlannerAgent
from app.agents.orchestrator import Orchestrator, validate_draft
from app.agents.place import PlaceAgent
from app.agents.planning import RULE_FALLBACK_WARNING, PlanningOrchestrator
from app.agents.recommendation import RecommendationAgent
from app.agents.rule_scheduler import rule_draft
from app.agents.self_check import review_draft
from app.agents.weather import WeatherAgent
from app.core.base import AgentError, Registry
from app.core.models import Place, PlaceResult, TripRequest, WeatherDay, WeatherResult
from app.memory.preferences import MemoryAgent
from app.tools.places.providers import DemoProvider


def place(ident, types):
    return Place(id=ident, name=ident, address="Huế", latitude=16.4, longitude=107.5, source="t", types=list(types))


PLACES = PlaceResult(places=[
    place("museum", ["museum"]), place("park", ["park"]), place("beach", ["beach"]), place("tomb", ["tomb"]),
    place("temple", ["temple"]), place("lunch-1", ["restaurant"]), place("lunch-2", ["restaurant"]),
    place("cafe", ["cafe"]), place("hotel", ["hotel"]),
])


def trip(days=2):
    start = date.today() + timedelta(days=3)
    return TripRequest(destination="Huế", start_date=start, end_date=start + timedelta(days=days - 1), travelers=2,
                       budget_vnd=5000000)


def test_rule_draft_passes_the_self_check_rules():
    t = trip()
    rainy = WeatherResult(days=[WeatherDay(date=t.start_date, weather_code=63)])
    draft = rule_draft(t, PLACES, rainy, wish_ids={"tomb"})
    validate_draft(t, draft, PLACES)
    checks = review_draft(draft, PLACES, rainy, [("“lăng”", "lăng", {"tomb"})])
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    day_one = [a.place_id for a in draft.days[0].activities]
    assert day_one[0] == "tomb" and "hotel" not in day_one
    assert sum(p in ("park", "beach") for p in day_one) <= 1  # rainy day


class FailingLLM:
    async def plan(self, data, context):
        raise RuntimeError("429 quota")


def registry(llm):
    reg = Registry()
    provider = DemoProvider()

    class Places(DemoProvider):
        async def search(self, trip):
            return PLACES

        async def search_places(self, query):
            return PlaceResult(places=[])

    provider = Places()
    for agent in [MemoryAgent(None), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(llm), BudgetAgent()]:
        reg.register(agent)
    return reg, provider


async def test_classic_orchestrator_falls_back_to_rules_when_the_llm_fails():
    reg, _ = registry(FailingLLM())
    plan = await Orchestrator(reg, "live").plan(trip())
    assert plan.warnings[0] == RULE_FALLBACK_WARNING and len(plan.draft.days) == 2


async def test_planning_orchestrator_falls_back_and_reports_it():
    reg, provider = registry(FailingLLM())
    plan = await PlanningOrchestrator(reg, provider, None, "live").plan(trip())
    assert plan.self_check.scheduled_by == "rules" and plan.warnings[0] == RULE_FALLBACK_WARNING


async def test_no_places_is_still_an_error_even_with_the_fallback():
    reg = Registry()

    class Empty(DemoProvider):
        async def search(self, trip):
            return PlaceResult(places=[])

    provider = Empty()
    for agent in [MemoryAgent(None), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(FailingLLM()), BudgetAgent()]:
        reg.register(agent)
    with pytest.raises(AgentError):
        await Orchestrator(reg, "live").plan(trip())
