from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.agents import AgentError
from app.models import Context
from app.specialists.budget import BudgetRequest, BudgetSpecialist, CostLine
from app.specialists.memory import MemoryRequest, MemorySpecialist
from app.specialists.weather import WeatherRequest, WeatherSpecialist


@pytest.mark.asyncio
async def test_budget_decimal_and_unknowns():
    data = BudgetRequest(
        budget_vnd="100",
        lines=[
            CostLine(
                id="meal",
                category="meals",
                unit_price_vnd="0.10",
                quantity=3,
                certainty="estimated",
                source="user_input",
            ),
            CostLine(id="hotel", category="accommodation", quantity=2, source="unknown"),
        ],
    )
    result = await BudgetSpecialist().run(data, Context())
    assert result.subtotal_vnd == Decimal("0.30")
    assert result.status == "incomplete"
    assert result.unknown_line_ids == ["hotel"]
    assert result.missing_categories == ["transport", "visits"]


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,status", [("1", "over_budget"), ("100", "within_estimate")])
async def test_budget_complete_and_over_budget(budget, status):
    data = BudgetRequest(
        budget_vnd=budget,
        required_categories=["meals"],
        lines=[
            CostLine(
                id="a",
                category="meals",
                unit_price_vnd="20",
                quantity=2,
                certainty="quoted",
                source="user_quote",
            )
        ],
    )
    assert (await BudgetSpecialist().run(data, Context())).status == status


def test_budget_rejects_unknown_price_claim():
    with pytest.raises(ValidationError):
        CostLine(id="x", category="meals", quantity=1, unit_price_vnd=0, source="unknown")


@pytest.mark.asyncio
async def test_memory_consent_versions_and_user_isolation(tmp_path):
    path = tmp_path / "test.sqlite3"
    user = uuid4()
    memory = MemorySpecialist(path, user)
    with pytest.raises(AgentError, match="confirmation"):
        await memory.run(MemoryRequest(operation="save", preferences=["museums"]), Context())
    saved = await memory.run(
        MemoryRequest(operation="save", preferences=["museums"], confirmed=True), Context()
    )
    assert saved.version == 1
    reopened = MemorySpecialist(path, user)
    assert (await reopened.run(MemoryRequest(operation="read"), Context())).preferences == ["museums"]
    other = MemorySpecialist(path, uuid4())
    assert (await other.run(MemoryRequest(operation="read"), Context())).status == "empty"
    with pytest.raises(AgentError, match="version conflict"):
        await reopened.run(MemoryRequest(operation="save", confirmed=True), Context())
    forgotten = await reopened.run(
        MemoryRequest(operation="forget", confirmed=True, expected_version=1), Context()
    )
    assert forgotten.preferences == []
    assert (await reopened.run(MemoryRequest(operation="read"), Context())).status == "empty"


@pytest.mark.asyncio
async def test_memory_expiration(tmp_path):
    now = datetime(2030, 1, 1, tzinfo=UTC)
    memory = MemorySpecialist(tmp_path / "ttl.sqlite3", uuid4(), now=lambda: now)
    await memory.run(
        MemoryRequest(operation="save", confirmed=True, preferences=["beach"], ttl_days=1), Context()
    )
    now += timedelta(days=2)
    result = await memory.run(MemoryRequest(operation="read"), Context())
    assert result.preferences == []
    assert result.version == 1


@pytest.mark.asyncio
async def test_weather_coordinates_and_missing_data():
    now = datetime(2030, 1, 1, tzinfo=UTC)

    def handler(request):
        assert request.url.params["latitude"] == "16.0"
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2030-01-01", "2030-01-02"],
                    "weather_code": [95, None],
                    "precipitation_probability_max": [80, None],
                }
            },
        )

    agent = WeatherSpecialist(httpx.MockTransport(handler), now=lambda: now)
    data = WeatherRequest(latitude=16, longitude=108, start_date="2030-01-01", end_date="2030-01-03")
    result = await agent.run(data, Context())
    assert result.status == "partial"
    assert result.days[0].outdoor_risk == "elevated"
    assert result.days[1].outdoor_risk == "unknown"
    assert len(result.missing_dates) == 1


@pytest.mark.asyncio
async def test_outside_horizon_makes_no_network_call():
    def handler(request):
        pytest.fail("Out-of-range dates must not call provider")

    agent = WeatherSpecialist(httpx.MockTransport(handler), now=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    result = await agent.run(
        WeatherRequest(latitude=16, longitude=108, start_date="2030-03-01", end_date="2030-03-02"), Context()
    )
    assert result.status == "outside_forecast"


@pytest.mark.asyncio
async def test_bad_weather_response_is_not_empty_forecast():
    agent = WeatherSpecialist(
        httpx.MockTransport(lambda req: httpx.Response(200, json={})),
        now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(AgentError):
        await agent.run(
            WeatherRequest(latitude=16, longitude=108, start_date="2030-01-01", end_date="2030-01-01"),
            Context(),
        )
