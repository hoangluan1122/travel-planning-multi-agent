"""Scripted model for LLM-agent tests: replays tool calls through Microsoft Agent Framework's real
function-invocation loop, so budgets, the submit gate and middleware run exactly as in production."""

import json
from datetime import timedelta

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)
from test_planning import payload

from app.core.models import PlannerInput, TripRequest, WeatherResult
from app.tools.places.providers import DemoProvider


async def fixture_data():
    trip = TripRequest(**payload())
    places = await DemoProvider().search(trip)
    data = PlannerInput(trip=trip, places=places, weather=WeatherResult())
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
