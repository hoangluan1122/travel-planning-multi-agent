"""Orchestrator and WorkflowOrchestrator must behave identically.

Each scenario runs on both; the workflow-only tests check the graph itself
(fan-out concurrency, checkpoints, per-request isolation).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from test_planning import payload

pytest.importorskip("agent_framework")

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
from app.main import Settings, create_app
from app.models import Activity, Day, Draft, Preferences, TripRequest
from app.orchestrator import Orchestrator
from app.providers import DemoProvider
from app.workflow_orchestrator import WorkflowOrchestrator

ORCHESTRATORS = [Orchestrator, WorkflowOrchestrator]


def registry(provider=None, memory=None, planner=None):
    provider = provider or DemoProvider()
    reg = Registry()
    for agent in [
        memory or MemoryAgent(),
        PlaceAgent(provider),
        WeatherAgent(provider),
        RecommendationAgent(),
        planner or PlannerAgent(),
        BudgetAgent(),
    ]:
        reg.register(agent)
    return reg


def trip(**overrides):
    return TripRequest(**{**payload(), **overrides})


def comparable(response):
    return response.model_dump(mode="json", exclude={"request_id"})


@pytest.mark.asyncio
async def test_both_orchestrators_produce_the_same_plan():
    classic = await Orchestrator(registry()).plan(trip())
    workflow = await WorkflowOrchestrator(registry()).plan(trip())
    assert comparable(workflow) == comparable(classic)
    assert workflow.draft.days and workflow.budget.status == "incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", ORCHESTRATORS)
async def test_weather_failure_preserves_draft(orchestrator):
    class FailedWeather(DemoProvider):
        async def forecast(self, trip):
            raise RuntimeError("provider down")

    result = await orchestrator(registry(FailedWeather())).plan(trip())
    assert result.draft.days
    assert not result.weather.days
    assert any("thất bại" in warning for warning in result.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", ORCHESTRATORS)
async def test_place_failure_stops_plan_without_leaking_cause(orchestrator):
    class FailedPlaces(DemoProvider):
        async def search(self, trip):
            raise RuntimeError("private provider detail")

    with pytest.raises(AgentError, match="Place lookup failed") as info:
        await orchestrator(registry(FailedPlaces())).plan(trip())
    assert "private provider detail" not in str(info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", ORCHESTRATORS)
async def test_place_timeout_is_a_timeout(orchestrator):
    class SlowPlaces(DemoProvider):
        async def search(self, trip):
            await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await orchestrator(registry(SlowPlaces()), timeout=0.05).plan(trip())


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", ORCHESTRATORS)
async def test_invented_place_is_rejected_by_validation_step(orchestrator):
    class InventingPlanner(PlannerAgent):
        async def execute(self, data, context):
            return Draft(
                days=[
                    Day(date=day, activities=[Activity(place_id="invented", start_minute=540, end_minute=600)])
                    for day in [data.trip.start_date, data.trip.end_date]
                ]
            )

    with pytest.raises(AgentError, match="invented an unknown place"):
        await orchestrator(registry(planner=InventingPlanner())).plan(trip())


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", ORCHESTRATORS)
async def test_memory_preferences_reach_recommendation(orchestrator):
    seen = []

    class RecordingMemory(MemoryAgent):
        async def execute(self, data, context):
            prefs = Preferences(interests=["museum"])
            seen.append(prefs)
            return prefs

    class RecordingRecommendation(RecommendationAgent):
        async def execute(self, data, context):
            seen.append(data.preferences)
            return await super().execute(data, context)

    reg = registry(memory=RecordingMemory())
    reg._agents["recommendation"] = RecordingRecommendation()
    await orchestrator(reg).plan(trip())
    assert seen[0] == seen[1] == Preferences(interests=["museum"])


@pytest.mark.asyncio
async def test_workflow_runs_place_and_weather_concurrently():
    both_started = asyncio.Event()
    started = []

    class Concurrent(DemoProvider):
        async def search(self, trip):
            started.append("place")
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return await super().search(trip)

        async def forecast(self, trip):
            started.append("weather")
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return await super().forecast(trip)

    # Sequential execution would time out waiting for the other branch to start.
    result = await WorkflowOrchestrator(registry(Concurrent())).plan(trip())
    assert sorted(started) == ["place", "weather"] and result.draft.days


@pytest.mark.asyncio
async def test_workflow_concurrent_requests_are_isolated():
    orchestrator = WorkflowOrchestrator(registry())
    short = trip()  # 2 days
    long = trip(end_date=str(short.start_date + (short.end_date - short.start_date) * 3))  # 4 days
    solo_short, solo_long = await orchestrator.plan(short), await orchestrator.plan(long)
    together = await asyncio.gather(orchestrator.plan(short), orchestrator.plan(long))
    assert len({r.request_id for r in together}) == 2
    assert [comparable(r) for r in together] == [comparable(solo_short), comparable(solo_long)]
    assert len(together[0].draft.days) != len(together[1].draft.days)


@pytest.mark.asyncio
async def test_workflow_writes_checkpoints_when_storage_is_given():
    from agent_framework import InMemoryCheckpointStorage

    storage = InMemoryCheckpointStorage()
    result = await WorkflowOrchestrator(registry(), checkpoint_storage=storage).plan(trip())
    assert result.draft.days
    assert await storage.list_checkpoints(workflow_name="travelmate_plan")


def test_api_uses_workflow_orchestrator_when_configured():
    settings = Settings(_env_file=None, travelmate_orchestrator="workflow")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/plans/preview", json=payload())
    assert response.status_code == 200, response.text
    assert len(response.json()["draft"]["days"]) == 2
