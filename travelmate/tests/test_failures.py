import asyncio

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
from app.models import Context, TripRequest
from app.orchestrator import Orchestrator
from app.providers import DemoProvider


class FailedWeather(DemoProvider):
    async def forecast(self, trip):
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_weather_failure_preserves_draft():
    provider = FailedWeather()
    registry = Registry()
    for agent in [
        MemoryAgent(),
        PlaceAgent(provider),
        WeatherAgent(provider),
        RecommendationAgent(),
        PlannerAgent(),
        BudgetAgent(),
    ]:
        registry.register(agent)
    result = await Orchestrator(registry).plan(TripRequest(**payload()))
    assert result.draft.days
    assert not result.weather.days
    assert any("thất bại" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_agent_timeout():
    class SlowMemory(MemoryAgent):
        async def execute(self, data, context):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await SlowMemory().run(TripRequest(**payload()), Context(), timeout=0.001)


def test_adk_schema_compatible():
    pytest.importorskip("google.adk")
    from google.adk.agents import LlmAgent

    from app.models import Draft

    agent = LlmAgent(name="planner_test", model="gemini-2.5-flash", output_schema=Draft)
    assert agent.output_schema is Draft
