import asyncio

import pytest
from test_planning import payload

from app.agents.budget import BudgetAgent
from app.agents.itinerary import PlannerAgent
from app.agents.orchestrator import Orchestrator
from app.agents.place import PlaceAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.weather import WeatherAgent
from app.core.base import Registry
from app.core.models import Context, TripRequest
from app.memory.preferences import MemoryAgent
from app.tools.places.providers import DemoProvider


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

    from app.core.models import Draft

    agent = LlmAgent(name="planner_test", model="gemini-2.5-flash", output_schema=Draft)
    assert agent.output_schema is Draft
