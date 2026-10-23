import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.agents import AgentError
from app.models import Context
from app.specialists.routing import (
    OSRMProvider,
    RoadPath,
    RouteMatrix,
    RouteReport,
    RouteRequest,
    RouteSpecialist,
    optimize,
)


def request(**changes):
    data = dict(
        origin={"id": "hotel", "latitude": 16, "longitude": 108},
        visits=[{"id": key, "latitude": 16, "longitude": 108, "duration_minutes": 30} for key in ["a", "b"]],
        departure_minute=540,
        finish_by_minute=1080,
    )
    data.update(changes)
    return RouteRequest.model_validate(data)


def matrix(endpoint=False):
    ids = ["hotel", "a", "b"] + (["airport"] if endpoint else [])
    n = len(ids)
    return RouteMatrix(
        point_ids=ids,
        durations_seconds=[[0 if i == j else 60 for j in range(n)] for i in range(n)],
        distances_m=[[0 if i == j else 1000 for j in range(n)] for i in range(n)],
        source="fixture",
        fetched_at=datetime.now(UTC),
    )


def test_buffers_waiting_and_time_balance():
    data = request(travel_buffer_minutes=5)
    data.visits[1].fixed_start_minute = 660
    result = optimize(data, matrix())
    assert result.status == "feasible" and len(result.legs) == 3
    assert result.travel_seconds == 180 and result.buffer_seconds == 900
    assert result.total_distance_m == 3000
    assert next(v for v in result.schedule if v.place_id == "b").start_second == 660 * 60
    assert result.finish_second - data.departure_minute * 60 == (
        result.travel_seconds + result.buffer_seconds + result.waiting_seconds + 60 * 60
    )
    assert result.legs[-1].to_id == "hotel"


def test_distinct_endpoint_is_included_in_matrix_and_day_end():
    data = request(return_to_origin=False, destination={"id": "airport", "latitude": 16, "longitude": 108})
    result = optimize(data, matrix(endpoint=True))
    assert result.legs[-1].to_id == "airport" and result.travel_seconds == 180
    data.finish_by_minute = 602
    assert optimize(data, matrix(endpoint=True)).status == "infeasible"


def test_open_route_ends_at_last_visit_without_phantom_return():
    result = optimize(request(return_to_origin=False), matrix())
    assert len(result.legs) == 2 and result.travel_seconds == 120


def test_precedence_and_locked_order():
    data = request(precedence=[{"before_id": "b", "after_id": "a"}])
    result = optimize(data, matrix())
    assert [v.place_id for v in result.schedule] == ["b", "a"]
    assert not result.baseline_feasible
    data.optimize_order = False
    report = optimize(data, matrix())
    assert report.status == "infeasible" and report.evaluated_orders == 1


def test_appointments_cannot_be_moved_to_hide_lateness():
    data = request()
    data.visits[0].fixed_start_minute = 540
    assert optimize(data, matrix()).status == "infeasible"


def test_buffer_can_make_previously_feasible_day_impossible():
    data = request(finish_by_minute=605)
    assert optimize(data, matrix()).status == "feasible"
    data.travel_buffer_minutes = 5
    assert optimize(data, matrix()).status == "infeasible"


@pytest.mark.parametrize(
    "changes",
    [
        {"precedence": [{"before_id": "a", "after_id": "b"}, {"before_id": "b", "after_id": "a"}]},
        {"precedence": [{"before_id": "a", "after_id": "unknown"}]},
        {"destination": {"id": "airport", "latitude": 16, "longitude": 108}},
        {"travel_buffer_minutes": True},
        {"include_geometry": "yes"},
    ],
)
def test_invalid_route_constraints(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_whitespace_ids_cannot_bypass_uniqueness_or_be_blank():
    data = request().model_dump()
    data["visits"][0]["id"] = " hotel "
    with pytest.raises(ValidationError):
        RouteRequest.model_validate(data)
    data["visits"][0]["id"] = " "
    with pytest.raises(ValidationError):
        RouteRequest.model_validate(data)


def test_matrix_rejects_boolean_and_mismatched_distance_reachability():
    raw = matrix().model_dump()
    raw["durations_seconds"][0][1] = True
    with pytest.raises(ValidationError):
        RouteMatrix.model_validate(raw)
    raw = matrix().model_dump()
    raw["distances_m"][0][1] = None
    with pytest.raises(ValidationError):
        RouteMatrix.model_validate(raw)


def provider_payload(points):
    n = len(points)
    waypoints = [{"location": [p.longitude, p.latitude], "distance": 0} for p in points]
    return {
        "code": "Ok",
        "durations": [[0 if i == j else 60 for j in range(n)] for i in range(n)],
        "distances": [[0 if i == j else 1000 for j in range(n)] for i in range(n)],
        "sources": waypoints,
        "destinations": waypoints,
    }


@pytest.mark.asyncio
async def test_real_provider_contract_cache_isolation_and_snap_validation():
    points = [request().origin, *request().visits]
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.params["annotations"] == "duration,distance"
        assert "TravelMate" in req.headers["user-agent"]
        return httpx.Response(200, json=provider_payload(points))

    provider = OSRMProvider(transport=httpx.MockTransport(handler))
    first = await provider.matrix(points)
    first.durations_seconds[0][1] = 99999
    second = await provider.matrix(points)
    assert len(calls) == 1 and second.durations_seconds[0][1] == 60
    assert first.fetched_at == second.fetched_at
    bad = provider_payload(points)
    bad["sources"][0]["distance"] = 500
    with pytest.raises(AgentError):
        await OSRMProvider(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=bad))).matrix(
            points
        )


@pytest.mark.asyncio
async def test_rate_limit_triggers_cooldown_not_retry_storm():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429)

    provider = OSRMProvider(transport=httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(AgentError):
            await provider.matrix([request().origin, *request().visits])
    assert len(calls) == 1


class Provider:
    def __init__(self, mismatch=False, failed=False):
        self.mismatch, self.failed = mismatch, failed

    async def matrix(self, points):
        return matrix()

    async def route(self, points):
        if self.failed:
            raise AgentError("unavailable")
        seconds = 300 if self.mismatch else 60
        return RoadPath(
            point_ids=[p.id for p in points],
            geometry={"type": "LineString", "coordinates": [[108, 16], [108.01, 16.01]]},
            distance_m=3000,
            duration_seconds=seconds * 3,
            leg_durations_seconds=[seconds] * 3,
            leg_distances_m=[1000] * 3,
            fetched_at=datetime.now(UTC),
            source="fixture",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch,failed,status",
    [(False, False, "available"), (True, False, "mismatch"), (False, True, "unavailable")],
)
async def test_geometry_outcome_is_separate_from_matrix_feasibility(mismatch, failed, status):
    result = await RouteSpecialist(Provider(mismatch, failed)).run(request(include_geometry=True), Context())
    assert result.status == "feasible" and result.geometry_status == status
    assert (result.path is not None) == (status == "available")


@pytest.mark.asyncio
async def test_osrm_geometry_payload_validation():
    data = request()
    points = [data.origin, data.visits[0], data.visits[1], data.origin]
    waypoints = [{"location": [p.longitude, p.latitude], "distance": 0} for p in points]
    payload = {
        "code": "Ok",
        "waypoints": waypoints,
        "routes": [
            {
                "duration": 180,
                "distance": 3000,
                "legs": [{"duration": 60, "distance": 1000}] * 3,
                "geometry": {"type": "LineString", "coordinates": [[108, 16], [108.01, 16.01]]},
            }
        ],
    }
    provider = OSRMProvider(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    result = await provider.route(points)
    assert result.geometry.coordinates[0] == (108, 16)
    payload["routes"][0]["duration"] = 999
    with pytest.raises(AgentError):
        await OSRMProvider(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
        ).route(points)


def test_replay_live_geometry_and_schedule_without_network():
    root = Path(__file__).parents[1]
    raw = json.loads((root / "evaluation/route-day-live-2026-10-22.json").read_text(encoding="utf-8"))
    stored = RouteReport.model_validate(raw)
    data = RouteRequest.model_validate_json((root / "examples/route-day.json").read_text(encoding="utf-8"))
    result = optimize(data, stored.matrix)
    assert stored.geometry_status == "available" and stored.path is not None
    assert [v.place_id for v in result.schedule] == [v.place_id for v in stored.schedule]
    assert result.travel_seconds == stored.travel_seconds
    assert abs(result.total_distance_m - stored.path.distance_m) < 1


def test_route_api_auth_and_payload_without_gemini():
    from fastapi.testclient import TestClient

    from app.specialist_api import SpecialistSettings, create_app

    app = create_app(
        SpecialistSettings(travelmate_api_token="route-test"),
        overrides={"route": RouteSpecialist(Provider())},
    )
    with TestClient(app) as client:
        path, raw = "/api/v1/agents/routes", request().model_dump(mode="json")
        assert client.post(path, json=raw).status_code == 401
        response = client.post(path, json=raw, headers={"Authorization": "Bearer route-test"})
        assert response.status_code == 200 and response.json()["status"] == "feasible"
        assert (
            client.post(
                path,
                json={**raw, "travel_buffer_minutes": -1},
                headers={"Authorization": "Bearer route-test"},
            ).status_code
            == 422
        )
