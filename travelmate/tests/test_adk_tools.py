import json

import pytest
from test_planning import payload

pytest.importorskip("google.adk")
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.adk_adapter import AdkPlanner
from app.agents import AgentError
from app.models import Context, PlannerInput, TripRequest, WeatherResult
from app.providers import DemoProvider


class ScriptedModel(BaseLlm):
    model: str = "scripted-test"
    calls: list[dict]
    index: int = 0
    observations: list[dict] = []

    async def generate_content_async(self, llm_request, stream=False):
        for content in llm_request.contents:
            for part in content.parts or []:
                if part.function_response:
                    self.observations.append(part.function_response.response)
        call = self.calls[self.index] if self.index < len(self.calls) else None
        self.index += 1
        part = types.Part(function_call=types.FunctionCall(**call)) if call else types.Part(text="Done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def fixture_data():
    trip = TripRequest(**payload())
    places = await DemoProvider().search(trip)
    data = PlannerInput(trip=trip, places=places, weather=WeatherResult())
    from datetime import timedelta

    draft = {
        "days": [
            {
                "date": str(trip.start_date + timedelta(days=i)),
                "activities": [{"place_id": "demo-attraction", "start_minute": 540, "end_minute": 660}],
            }
            for i in range((trip.end_date - trip.start_date).days + 1)
        ]
    }
    return data, draft


@pytest.mark.asyncio
async def test_real_adk_runtime_repairs_invalid_tool_submission():
    data, draft = await fixture_data()
    invalid = json.loads(json.dumps(draft))
    invalid["days"][0]["activities"][0]["place_id"] = "hallucinated"
    model = ScriptedModel(
        calls=[
            {"name": "inspect_trip", "args": {}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(invalid)}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
        ]
    )
    result = await AdkPlanner(model).plan(data, Context())
    assert result.days[0].activities[0].place_id == "demo-attraction"
    assert any(o.get("accepted") is False for o in model.observations)
    assert model.index == 3


@pytest.mark.asyncio
async def test_unvalidated_text_is_not_a_plan():
    data, _ = await fixture_data()
    with pytest.raises(AgentError, match="without a validated"):
        await AdkPlanner(ScriptedModel(calls=[])).plan(data, Context())


@pytest.mark.asyncio
async def test_submission_budget_stops_repair_loop():
    data, _ = await fixture_data()
    model = ScriptedModel(
        calls=[
            {"name": "inspect_trip", "args": {}},
            *[{"name": "submit_itinerary", "args": {"draft_json": "{}"}}] * 4,
        ]
    )
    with pytest.raises(AgentError, match="submission budget"):
        await AdkPlanner(model).plan(data, Context())


@pytest.mark.asyncio
async def test_submission_requires_evidence_read():
    data, draft = await fixture_data()
    model = ScriptedModel(
        calls=[
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
        ]
    )
    with pytest.raises(AgentError, match="without a validated"):
        await AdkPlanner(model).plan(data, Context())
    assert any(o.get("error") == "Call inspect_trip first." for o in model.observations)


@pytest.mark.asyncio
async def test_llm_call_limit_stops_loop():
    data, _ = await fixture_data()
    model = ScriptedModel(calls=[{"name": "inspect_trip", "args": {}}] * 3)
    with pytest.raises(AgentError, match="model-call budget"):
        await AdkPlanner(model, max_llm_calls=2).plan(data, Context())
    assert model.index == 2


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_results():
    import asyncio

    async def run(place_id):
        data, draft = await fixture_data()
        data.places.places[0].id = place_id
        for day in draft["days"]:
            day["activities"][0]["place_id"] = place_id
        model = ScriptedModel(
            calls=[
                {"name": "inspect_trip", "args": {}},
                {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
            ]
        )
        return await AdkPlanner(model).plan(data, Context())

    first, second = await asyncio.gather(run("first"), run("second"))
    assert first.days[0].activities[0].place_id == "first"
    assert second.days[0].activities[0].place_id == "second"
