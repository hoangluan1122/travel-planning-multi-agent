import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.agents import AgentError, BaseAgent
from app.models import Context, Model, Place, ScheduleConstraints
from app.provider_http import get_with_retry
from app.specialists.budget import BudgetRequest, BudgetSpecialist
from app.specialists.memory import MemoryConflictError, MemoryRequest, MemorySpecialist
from app.specialists.recommendation import RecommendationRequest
from app.specialists.weather import WeatherRequest, WeatherSpecialist


def place(identifier="p1"):
    return Place(id=identifier, name="Fixture", address="", latitude=0, longitude=0, source="test")


class Echo(BaseAgent):
    name, input_schema, output_schema = "echo", RecommendationRequest, RecommendationRequest

    async def execute(self, data, context):
        data.candidates[0].name = "Changed inside agent"
        return data


@pytest.mark.asyncio
async def test_runtime_isolates_caller_owned_nested_state():
    data = RecommendationRequest(candidates=[place()])
    result = await Echo().run(data, Context())
    assert result.candidates[0].name == "Changed inside agent"
    assert data.candidates[0].name == "Fixture"


@pytest.mark.asyncio
async def test_runtime_revalidates_mutated_input_and_output():
    data = RecommendationRequest(candidates=[place()])
    data.limit = -1
    with pytest.raises(ValidationError):
        await Echo().run(data, Context())

    class Invalid(Echo):
        async def execute(self, data, context):
            data.candidates[0].latitude = 999
            return data

    with pytest.raises(ValidationError):
        await Invalid().run(RecommendationRequest(candidates=[place()]), Context())


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
async def test_runtime_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        await Echo().run(RecommendationRequest(candidates=[place()]), Context(), timeout)


@pytest.mark.asyncio
async def test_cancellation_propagates_and_cleanup_runs():
    started, cleaned = asyncio.Event(), asyncio.Event()

    class Slow(BaseAgent):
        name, input_schema, output_schema = "slow", Model, Model

        async def execute(self, data, context):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                cleaned.set()

    task = asyncio.create_task(Slow().run(Model(), Context()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


@pytest.mark.parametrize(
    "fields",
    [
        {"required_place_ids": ["missing"]},
        {"required_place_ids": ["p1"], "excluded_place_ids": ["p1"]},
        {"excluded_place_ids": ["p1"]},
        {"interests": ["   "]},
    ],
)
def test_recommendation_rejects_contradictory_or_empty_inputs(fields):
    with pytest.raises(ValidationError):
        RecommendationRequest(candidates=[place()], **fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"required_place_ids": ["p1"], "excluded_place_ids": ["p1"]},
        {"day_start_minute": 600, "day_end_minute": 610, "min_activity_minutes": 20},
        {"required_place_ids": ["p1", "p1"]},
    ],
)
def test_impossible_schedule_constraints_rejected(fields):
    with pytest.raises(ValidationError):
        ScheduleConstraints(**fields)


@pytest.mark.parametrize("value", ["true", "yes", 1])
def test_memory_consent_must_be_boolean(value):
    with pytest.raises(ValidationError):
        MemoryRequest(operation="save", confirmed=value)


@pytest.mark.asyncio
async def test_concurrent_memory_writes_have_one_winner(tmp_path):
    agent = MemorySpecialist(tmp_path / "race.sqlite3", uuid4())
    await agent.run(MemoryRequest(operation="read"), Context())
    results = await asyncio.gather(
        *[
            agent.run(MemoryRequest(operation="save", confirmed=True, preferences=[pref]), Context())
            for pref in ["beach", "museum"]
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, MemoryConflictError) for r in results) == 1
    current = await agent.run(MemoryRequest(operation="read"), Context())
    assert current.version == 1 and current.preferences in [["beach"], ["museum"]]


@pytest.mark.asyncio
async def test_budget_breakdown_balances_and_unknowns_stay_unknown():
    report = await BudgetSpecialist().run(
        BudgetRequest(
            budget_vnd="10",
            lines=[
                {
                    "id": "quoted",
                    "category": "meals",
                    "unit_price_vnd": "0.10",
                    "quantity": 3,
                    "source": "user",
                    "certainty": "quoted",
                },
                {
                    "id": "estimate",
                    "category": "meals",
                    "unit_price_vnd": "1.20",
                    "quantity": 2,
                    "source": "user",
                    "certainty": "estimated",
                },
                {"id": "unknown", "category": "transport", "quantity": 1, "source": "missing"},
            ],
        ),
        Context(),
    )
    assert report.subtotal_vnd == Decimal("2.70")
    assert report.quoted_subtotal_vnd + report.estimated_subtotal_vnd == report.subtotal_vnd
    assert sum(report.category_subtotals.values()) == report.subtotal_vnd
    assert report.line_totals["unknown"] is None
    assert report.status == "incomplete"


@pytest.mark.asyncio
async def test_retry_transient_get_then_success():
    calls, waits = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, json={})

    async def sleep(seconds):
        waits.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        _, attempts = await get_with_retry(client, "https://example.test", params={}, sleep=sleep)
    assert attempts == 3 and waits == [0.2, 0.4]


@pytest.mark.asyncio
async def test_quota_response_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_with_retry(client, "https://example.test", params={})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code,rain", [(True, 20), (0, True), ("0", 20), (0, 101), (0, -1)])
async def test_weather_malformed_values_fail_closed(code, rain):
    agent = WeatherSpecialist(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "daily": {
                        "time": ["2030-01-01"],
                        "weather_code": [code],
                        "precipitation_probability_max": [rain],
                    }
                },
            )
        ),
        now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(AgentError):
        await agent.run(
            WeatherRequest(latitude=16, longitude=108, start_date="2030-01-01", end_date="2030-01-01"),
            Context(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "constraints",
    [
        {"day_start_minute": 600},
        {"day_end_minute": 600},
        {"min_activity_minutes": 121},
        {"excluded_place_ids": ["demo-attraction"]},
        {"required_place_ids": ["another-place"]},
        {
            "visit_windows": {
                "demo-attraction": {"opens_minute": 600, "closes_minute": 800, "source": "fixture"}
            }
        },
    ],
)
async def test_planner_validator_enforces_each_constraint(constraints):
    from test_adk_tools import fixture_data

    from app.models import Draft
    from app.orchestrator import validate_draft

    data, draft = await fixture_data()
    with pytest.raises(AgentError):
        validate_draft(
            data.trip, Draft.model_validate(draft), data.places, ScheduleConstraints(**constraints)
        )
