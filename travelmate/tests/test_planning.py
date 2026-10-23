from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.agents import AgentError, MemoryAgent, Registry
from app.main import Settings, create_app
from app.models import Activity, Day, Draft, PlaceResult, TripRequest
from app.orchestrator import validate_draft


def payload():
    return dict(
        destination="Da Nang",
        start_date=str(date.today() + timedelta(days=2)),
        end_date=str(date.today() + timedelta(days=3)),
        travelers=2,
        budget_vnd="6000000",
    )


def test_demo_complete_pipeline():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post("/api/v1/plans/preview", json=payload())
    assert response.status_code == 200
    body = response.json()
    assert len(body["draft"]["days"]) == 2
    assert body["mode"] == "demo"
    assert body["budget"]["status"] == "incomplete"
    assert Decimal(body["budget"]["known_subtotal"]) == 0
    assert body["budget"]["unknown_items"]


@pytest.mark.parametrize(
    "field,value", [("travelers", 0), ("budget_vnd", -1), ("destination", "  "), ("end_date", "2000-01-01")]
)
def test_invalid_request(field, value):
    data = payload()
    data[field] = value
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.post("/api/v1/plans/preview", json=data).status_code == 422


def test_token_required_when_configured():
    with TestClient(create_app(Settings(_env_file=None, travelmate_api_token="test-secret"))) as client:
        assert client.post("/api/v1/plans/preview", json=payload()).status_code == 401
        assert (
            client.post(
                "/api/v1/plans/preview", json=payload(), headers={"Authorization": "Bearer test-secret"}
            ).status_code
            == 200
        )


def test_duplicate_agent_rejected():
    registry = Registry()
    registry.register(MemoryAgent())
    with pytest.raises(ValueError):
        registry.register(MemoryAgent())


def test_invented_place_rejected():
    trip = TripRequest(**payload())
    draft = Draft(
        days=[
            Day(
                date=trip.start_date + timedelta(days=i),
                activities=[Activity(place_id="invented", start_minute=540, end_minute=600)],
            )
            for i in range(2)
        ]
    )
    with pytest.raises(AgentError, match="unknown place"):
        validate_draft(trip, draft, PlaceResult(places=[]))


def test_missing_day_rejected():
    trip = TripRequest(**payload())
    draft = Draft(
        days=[
            Day(date=trip.start_date, activities=[Activity(place_id="x", start_minute=540, end_minute=600)])
        ]
    )
    with pytest.raises(AgentError, match="missing"):
        validate_draft(trip, draft, PlaceResult(places=[]))


def test_live_fails_without_credentials():
    with pytest.raises(ValueError):
        create_app(
            Settings(
                _env_file=None,
                travelmate_mode="live",
                google_api_key="",
                google_maps_api_key="",
                travelmate_api_token="",
            )
        )
