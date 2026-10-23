from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.agents import AgentError
from app.specialists.routing import OSRMProvider, RouteMatrix, RouteRequest, optimize


def request():
    return RouteRequest(
        origin={"id": "origin", "latitude": 0, "longitude": 0},
        visits=[{"id": p, "latitude": 0, "longitude": 0, "duration_minutes": 30} for p in ["a", "b", "c"]],
    )


def matrix(rows):
    return RouteMatrix(
        point_ids=["origin", "a", "b", "c"],
        durations_seconds=rows,
        source="fixture",
        fetched_at=datetime.now(UTC),
    )


def test_directed_exact_improvement():
    result = optimize(
        request(), matrix([[0, 100, 10, 100], [10, 0, 100, 100], [100, 100, 0, 10], [100, 10, 100, 0]])
    )
    assert [v.place_id for v in result.schedule] == ["b", "c", "a"]
    assert result.travel_seconds == 40
    assert result.baseline_travel_seconds == 310
    assert result.evaluated_orders == 6


def test_unreachable_is_not_zero_cost():
    result = optimize(request(), matrix([[0, None, None, None], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]]))
    assert result.status == "infeasible"
    assert result.travel_seconds is None


def test_visit_windows_include_waiting_and_service():
    data = request()
    data.visits[0].opens_minute = 660
    result = optimize(data, matrix([[0, 60, 60, 60], [60, 0, 60, 60], [60, 60, 0, 60], [60, 60, 60, 0]]))
    a = next(v for v in result.schedule if v.place_id == "a")
    assert a.start_second >= 660 * 60
    assert a.end_second - a.start_second == 30 * 60


def test_impossible_finish_is_explicit():
    data = request()
    data.finish_by_minute = 550
    assert optimize(data, matrix([[0] * 4 for _ in range(4)])).status == "infeasible"


def test_visit_longer_than_window_is_infeasible_not_schema_error():
    from app.specialists.routing import Visit

    data = request()
    data.visits[0] = Visit(
        id="a", latitude=0, longitude=0, duration_minutes=120, opens_minute=600, closes_minute=630
    )
    result = optimize(data, matrix([[0] * 4 for _ in range(4)]))
    assert result.status == "infeasible"
    assert result.schedule == []


def test_matrix_rejects_bad_dimensions_and_nan():
    with pytest.raises(ValidationError):
        matrix([[0]])
    with pytest.raises(ValidationError):
        matrix([[float("nan")] * 4 for _ in range(4)])


@pytest.mark.asyncio
async def test_provider_does_not_mask_failure():
    provider = OSRMProvider(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": "NoTable"}))
    )
    with pytest.raises(AgentError):
        await provider.matrix([request().origin, *request().visits])
