import asyncio
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from app.specialist_api import SpecialistSettings, create_app

HEADERS = {"Authorization": "Bearer local-test-token"}
BUDGET = {"budget_vnd": "1000", "lines": []}


def settings(tmp_path, **kwargs):
    return SpecialistSettings(
        _env_file=None,
        travelmate_api_token="local-test-token",
        specialist_memory_db=tmp_path / "memory.sqlite3",
        specialist_memory_user=UUID("11111111-1111-4111-8111-111111111111"),
        google_api_key="",
        **kwargs,
    )


def test_budget_auth_schema_and_unknown_costs(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.post("/api/v1/agents/budget", json=BUDGET).status_code == 401
        response = client.post("/api/v1/agents/budget", headers=HEADERS, json=BUDGET)
        assert response.status_code == 200
        assert response.json()["status"] == "incomplete"
        assert UUID(response.headers["X-Request-ID"])
        assert (
            client.post(
                "/api/v1/agents/budget", headers=HEADERS, json={**BUDGET, "budget_vnd": -1}
            ).status_code
            == 422
        )


def test_memory_consent_conflict_and_body_identity_rejected(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:

        def call(data):
            return client.post("/api/v1/agents/memory", headers=HEADERS, json=data)

        assert call({"operation": "save", "preferences": ["Quiet"]}).status_code == 422
        assert call({"operation": "read", "user_id": "someone-else"}).status_code == 422
        saved = call({"operation": "save", "preferences": ["Quiet"], "confirmed": True})
        assert saved.json()["version"] == 1
        assert call({"operation": "save", "confirmed": True}).status_code == 409
        assert call({"operation": "read"}).json()["preferences"] == ["Quiet"]
        assert call({"operation": "forget", "confirmed": True, "expected_version": 1}).status_code == 200
        assert call({"operation": "read"}).json()["preferences"] == []


def test_missing_gemini_is_explicit_not_fake_ranking(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agents/recommendation",
            headers=HEADERS,
            json={
                "candidates": [
                    {
                        "id": "p1",
                        "name": "Fixture",
                        "address": "Fixture",
                        "latitude": 0,
                        "longitude": 0,
                        "source": "test",
                    }
                ]
            },
        )
        assert response.status_code == 503


def test_provider_error_does_not_leak_secret(tmp_path):
    class Failed:
        async def run(self, *args):
            raise RuntimeError("https://provider.test/?key=SECRET")

    with TestClient(create_app(settings(tmp_path), {"budget": Failed()})) as client:
        response = client.post("/api/v1/agents/budget", headers=HEADERS, json=BUDGET)
        assert response.status_code == 502
        assert "SECRET" not in response.text


@pytest.mark.asyncio
async def test_concurrency_limit_and_release_after_timeout(tmp_path):
    started = asyncio.Event()

    class Slow:
        async def run(self, *args):
            started.set()
            await asyncio.sleep(10)

    app = create_app(settings(tmp_path, specialist_timeout=0.1, specialist_concurrency=1), {"budget": Slow()})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = asyncio.create_task(client.post("/api/v1/agents/budget", headers=HEADERS, json=BUDGET))
        await started.wait()
        second = await client.post("/api/v1/agents/budget", headers=HEADERS, json=BUDGET)
        assert second.status_code == 429
        assert (await first).status_code == 504
        assert (await client.post("/api/v1/agents/budget", headers=HEADERS, json=BUDGET)).status_code == 504


def test_weather_outside_horizon_needs_no_external_call(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agents/weather",
            headers=HEADERS,
            json={
                "latitude": 16.05,
                "longitude": 108.2,
                "start_date": "2099-01-01",
                "end_date": "2099-01-02",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "outside_forecast"
        assert len(response.json()["missing_dates"]) == 2
