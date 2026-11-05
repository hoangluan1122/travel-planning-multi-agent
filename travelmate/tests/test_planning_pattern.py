"""Planning pattern: structured plan, submit gate, dependency execution, re-planning."""

import json

import pytest
from test_planning import payload

from app.agents import (
    AgentError,
    BudgetAgent,
    MemoryAgent,
    PlaceAgent,
    PlannerAgent,
    RecommendationAgent,
    Registry,
    WeatherAgent,
)
from app.models import Place, PlaceResult, TravelPlan, TripRequest
from app.planning import PlanningAgent, PlanningOrchestrator, default_plan
from app.providers import DemoProvider


def plan_dict(searches=()):
    subtasks = [
        {"id": "places", "agent": "places", "goal": "broad search"},
        {"id": "weather", "agent": "weather", "goal": "forecast"},
        *[{"id": f"s{i}", "agent": "place_search", "goal": "need", "inputs": {"category": c, "keyword": k}}
          for i, (c, k) in enumerate(searches)],
        {"id": "rank", "agent": "recommendation", "goal": "rank",
         "depends_on": ["places", *[f"s{i}" for i in range(len(searches))]]},
        {"id": "schedule", "agent": "itinerary", "goal": "days", "depends_on": ["rank", "weather"]},
        {"id": "cost", "agent": "budget", "goal": "cost", "depends_on": ["schedule"]},
    ]
    return {"subtasks": subtasks}


# --- Submit gate ---------------------------------------------------------------------


def test_valid_plans_pass_the_gate():
    assert len(TravelPlan.model_validate(plan_dict([("restaurant", "chay")])).of("place_search")) == 1
    assert default_plan(TripRequest(**payload())).of("itinerary")


@pytest.mark.parametrize("mutate,error", [
    (lambda p: p["subtasks"].pop(1), "Exactly one subtask"),  # no weather
    (lambda p: p["subtasks"][2]["inputs"].update(keyword=""), "needs a category and a keyword"),
    (lambda p: p["subtasks"][3]["depends_on"].remove("s0"), "every place_search"),
    (lambda p: p["subtasks"][4]["depends_on"].remove("weather"), "must depend on a weather"),
    (lambda p: p["subtasks"][0].update(depends_on=["cost"]), "cycle"),
    (lambda p: p["subtasks"][1].update(id="places"), "unique"),
    (lambda p: p["subtasks"][5].update(depends_on=["nowhere"]), "unknown"),
])
def test_gate_rejects_unexecutable_plans(mutate, error):
    raw = plan_dict([("restaurant", "chay")])
    mutate(raw)
    with pytest.raises(ValueError, match=error):
        TravelPlan.model_validate(raw)


# --- Planning Agent on both engines ----------------------------------------------------


def calls_for(plan):
    bad = plan_dict([("restaurant", "")])
    return [
        {"name": "inspect_request", "args": {}},
        {"name": "submit_plan", "args": {"plan_json": json.dumps(bad)}},
        {"name": "submit_plan", "args": {"plan_json": json.dumps(plan)}},
    ]


@pytest.mark.asyncio
async def test_planning_agent_repairs_a_rejected_plan_on_adk():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    model = ScriptedModel(calls=calls_for(plan_dict([("restaurant", "chay")])))
    plan = await PlanningAgent(lambda: model, engine="adk").plan(TripRequest(**payload()), _ctx())
    assert plan.of("place_search")[0].inputs.keyword == "chay"
    assert any(o.get("accepted") is False for o in model.observations)


@pytest.mark.asyncio
async def test_planning_agent_repairs_a_rejected_plan_on_maf():
    pytest.importorskip("agent_framework")
    from test_maf_tools import ScriptedClient

    client = ScriptedClient(calls_for(plan_dict([("attraction", "lăng")])))
    plan = await PlanningAgent(lambda: client, engine="maf").plan(TripRequest(**payload()), _ctx())
    assert plan.of("place_search")[0].inputs.category == "attraction"
    assert client.index == 3  # stops right after acceptance


def _ctx():
    from app.models import Context

    return Context()


# --- Orchestrator --------------------------------------------------------------------


def place(ident, name, types=("restaurant",)):
    return Place(id=ident, name=name, address="a", latitude=16.05, longitude=108.2, source="t", types=list(types))


class Provider(DemoProvider):
    def __init__(self, found=None):
        self.found = found or {}
        self.queries = []

    async def search_places(self, query):
        self.queries.append((query.category, query.keyword))
        return PlaceResult(places=self.found.get(query.keyword, []))


class ScriptedPlanner:
    def __init__(self, plans, fail=False):
        self.plans, self.fail, self.calls = list(plans), fail, []

    async def plan(self, trip, context, previous=None, observations=()):
        self.calls.append([o.model_dump() for o in observations])
        if self.fail:
            raise AgentError("planner down")
        return TravelPlan.model_validate(self.plans.pop(0))


def orchestrator(provider, planner):
    registry = Registry()
    for agent in [MemoryAgent(), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(), BudgetAgent()]:
        registry.register(agent)
    return PlanningOrchestrator(registry, provider, planner)


@pytest.mark.asyncio
async def test_targeted_search_results_come_first_and_shape_preferences():
    provider = Provider({"chay": [place("v1", "Quán Chay A")]})
    planner = ScriptedPlanner([plan_dict([("restaurant", "chay")])])
    result = await orchestrator(provider, planner).plan(TripRequest(**payload()))
    assert provider.queries == [("restaurant", "chay")]
    assert result.places[0].id == "v1"
    assert result.planning.planner == "llm" and len(result.planning.rounds) == 1
    assert result.planning.rounds[0].observations[0].outcome == "ok"


@pytest.mark.asyncio
async def test_empty_search_triggers_one_replan_with_observations():
    provider = Provider({"vegan": [place("v2", "Vegan House")]})
    planner = ScriptedPlanner([plan_dict([("restaurant", "chay")]), plan_dict([("restaurant", "vegan")])])
    result = await orchestrator(provider, planner).plan(TripRequest(**payload()))
    assert provider.queries == [("restaurant", "chay"), ("restaurant", "vegan")]
    assert planner.calls[1] == [{"subtask_id": "s0", "outcome": "no_results", "count": 0}]
    rounds = result.planning.rounds
    assert [r.round for r in rounds] == [1, 2] and rounds[1].observations[0].outcome == "ok"
    assert any(p.id == "v2" for p in result.places)


@pytest.mark.asyncio
async def test_replanning_is_bounded():
    planner = ScriptedPlanner([plan_dict([("restaurant", "x")]), plan_dict([("restaurant", "y")]),
                               plan_dict([("restaurant", "z")])])
    result = await orchestrator(Provider(), planner).plan(TripRequest(**payload()))
    assert len(result.planning.rounds) == 3 and len(planner.calls) == 3  # first plan + 2 replans


@pytest.mark.asyncio
async def test_planner_failure_falls_back_to_the_core_plan():
    result = await orchestrator(Provider(), ScriptedPlanner([], fail=True)).plan(TripRequest(**payload()))
    assert result.planning.planner == "default" and result.draft.days
    assert not result.planning.rounds[0].plan.of("place_search")


@pytest.mark.asyncio
async def test_without_a_planner_the_default_plan_runs():
    result = await orchestrator(Provider(), None).plan(TripRequest(**payload()))
    assert result.planning.planner == "default" and result.budget.status


def test_api_runs_the_planning_orchestrator_in_demo_mode():
    from fastapi.testclient import TestClient

    from app.main import Settings, create_app

    with TestClient(create_app(Settings(_env_file=None, travelmate_orchestrator="planning"))) as client:
        response = client.post("/api/v1/plans/preview", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planning"]["planner"] == "default" and body["draft"]["days"]


def test_inputs_are_dropped_from_non_search_subtasks():
    raw = plan_dict([("restaurant", "chay")])
    raw["subtasks"][1]["inputs"] = {"category": "attraction", "keyword": ""}  # weather
    plan = TravelPlan.model_validate(raw)
    assert plan.of("weather")[0].inputs.category is None
    assert plan.of("place_search")[0].inputs.keyword == "chay"


@pytest.mark.asyncio
async def test_a_revision_with_nothing_new_is_still_recorded():
    planner = ScriptedPlanner([plan_dict([("restaurant", "chay")]), plan_dict([("restaurant", "chay")])])
    result = await orchestrator(Provider(), planner).plan(TripRequest(**payload()))
    rounds = result.planning.rounds
    assert len(rounds) == 2 and rounds[1].note and not rounds[1].observations


@pytest.mark.asyncio
async def test_a_hanging_planner_times_out_and_falls_back():
    import asyncio

    class Hanging:
        async def plan(self, *args):
            await asyncio.sleep(30)

    orch = orchestrator(Provider(), Hanging())
    orch.timeout = 0.2
    result = await orch.plan(TripRequest(**payload()))
    assert result.planning.planner == "default" and result.draft.days
