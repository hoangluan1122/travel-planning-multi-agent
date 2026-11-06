"""MafPlanner must enforce the same submit gate and budgets as AdkPlanner."""

import asyncio
import json

import pytest
from test_adk_tools import fixture_data

pytest.importorskip("agent_framework")
from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from app.core.base import AgentError
from app.core.llm.maf_adapter import MafPlanner
from app.core.models import Context


class ScriptedClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Replays scripted tool calls through MAF's real function-invocation loop."""

    def __init__(self, calls):
        super().__init__()
        self.calls = calls
        self.index = 0
        self.observations = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        assert not stream
        for message in messages:
            for content in message.contents:
                if content.type == "function_result" and content.call_id.startswith(f"r{self.index - 1}-"):
                    result = content.result
                    try:
                        result = json.loads(result) if isinstance(result, str) else result
                    except ValueError:
                        result = {"raw": result}
                    self.observations.append(result)
        call = self.calls[self.index] if self.index < len(self.calls) else None
        if call is not None and options.get("tool_choice") == "none":
            call = None  # MAF's forced final turn disables tools
        self.index += 1
        if call is None:
            content = Content.from_text("Done")
        else:
            content = Content.from_function_call(
                f"r{self.index - 1}-{call['name']}", call["name"], arguments=call["args"]
            )
        return ChatResponse(messages=[Message(role="assistant", contents=[content])])


def factory(client):
    return lambda: client


@pytest.mark.asyncio
async def test_maf_runtime_repairs_invalid_tool_submission():
    data, draft = await fixture_data()
    invalid = json.loads(json.dumps(draft))
    invalid["days"][0]["activities"][0]["place_id"] = "hallucinated"
    client = ScriptedClient(
        [
            {"name": "inspect_trip", "args": {}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(invalid)}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
        ]
    )
    result = await MafPlanner(factory(client)).plan(data, Context())
    assert result.days[0].activities[0].place_id == "demo-attraction"
    assert any(o.get("accepted") is False for o in client.observations)
    # Acceptance ends the loop: no extra model turn after the accepted submission.
    assert client.index == 3


@pytest.mark.asyncio
async def test_unvalidated_text_is_not_a_plan():
    data, _ = await fixture_data()
    with pytest.raises(AgentError, match="without a validated"):
        await MafPlanner(factory(ScriptedClient([]))).plan(data, Context())


@pytest.mark.asyncio
async def test_submission_budget_aborts_instead_of_feeding_error_to_model():
    data, _ = await fixture_data()
    client = ScriptedClient(
        [
            {"name": "inspect_trip", "args": {}},
            *[{"name": "submit_itinerary", "args": {"draft_json": "{}"}}] * 4,
            {"name": "inspect_trip", "args": {}},
        ]
    )
    with pytest.raises(AgentError, match="submission budget"):
        await MafPlanner(factory(client)).plan(data, Context())
    assert client.index == 5


@pytest.mark.asyncio
async def test_evidence_read_budget_aborts():
    data, _ = await fixture_data()
    client = ScriptedClient([{"name": "inspect_trip", "args": {}}] * 4)
    with pytest.raises(AgentError, match="evidence-read budget"):
        await MafPlanner(factory(client)).plan(data, Context())


@pytest.mark.asyncio
async def test_submission_requires_evidence_read():
    data, draft = await fixture_data()
    client = ScriptedClient([{"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}}])
    with pytest.raises(AgentError, match="without a validated"):
        await MafPlanner(factory(client)).plan(data, Context())
    assert any(o.get("error") == "Call inspect_trip first." for o in client.observations)


@pytest.mark.asyncio
async def test_llm_call_limit_stops_loop_without_extra_call():
    data, _ = await fixture_data()
    client = ScriptedClient([{"name": "inspect_trip", "args": {}}] * 3)
    with pytest.raises(AgentError, match="model-call budget"):
        await MafPlanner(factory(client), max_llm_calls=2).plan(data, Context())
    assert client.index == 2


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_results():
    async def run(place_id):
        data, draft = await fixture_data()
        data.places.places[0].id = place_id
        for day in draft["days"]:
            day["activities"][0]["place_id"] = place_id
        client = ScriptedClient(
            [
                {"name": "inspect_trip", "args": {}},
                {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
            ]
        )
        return await MafPlanner(factory(client)).plan(data, Context())

    first, second = await asyncio.gather(run("first"), run("second"))
    assert first.days[0].activities[0].place_id == "first"
    assert second.days[0].activities[0].place_id == "second"


@pytest.mark.asyncio
async def test_planner_specialist_runs_on_maf_engine():
    from app.specialists.planner import PlannerSpecialist

    data, draft = await fixture_data()
    client = ScriptedClient(
        [
            {"name": "inspect_trip", "args": {}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
        ]
    )
    result = await PlannerSpecialist(factory(client), MafPlanner).run(data, Context())
    assert result.days[0].activities[0].place_id == "demo-attraction"


def test_specialist_api_planner_engine_switch(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient
    from test_specialist_api import HEADERS, settings

    import app.specialists.api as api

    data, draft = asyncio.run(fixture_data())
    used = []

    @asynccontextmanager
    async def scripted_factory(_settings):
        used.append("maf")
        yield factory(
            ScriptedClient(
                [
                    {"name": "inspect_trip", "args": {}},
                    {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
                ]
            )
        )

    monkeypatch.setattr(api, "maf_gemini_factory", scripted_factory)
    with TestClient(api.create_app(settings(tmp_path, planner_engine="maf"))) as client:
        response = client.post("/api/v1/agents/planner", headers=HEADERS, json=data.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert used == ["maf"]
    assert response.json()["days"][0]["activities"][0]["place_id"] == "demo-attraction"


def test_limits_must_be_positive():
    with pytest.raises(ValueError):
        MafPlanner(lambda: None, max_llm_calls=0)
