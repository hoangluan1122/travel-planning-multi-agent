import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import AgentError
from app.main import Settings, create_app
from app.models import PlaceSearchRequest
from app.providers import LiveProvider


def record():
    return {
        "id": "real-provider-id",
        "displayName": {"text": "A provider result"},
        "location": {"latitude": 16.05, "longitude": 108.2},
        "types": ["hotel"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,term",
    [
        ("attraction", "Tourist attractions"),
        ("hotel", "Hotels"),
        ("restaurant", "Restaurants"),
    ],
)
async def test_category_queries_preserve_evidence(category, term):
    def handler(request):
        body = json.loads(request.content)
        assert body["textQuery"] == f"{term} in Da Nang, Vietnam"
        assert body["pageSize"] == 3
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        return httpx.Response(200, json={"places": [record(), record()]})

    provider = LiveProvider("test-key", transport=httpx.MockTransport(handler))
    result = await provider.search_places(
        PlaceSearchRequest(destination="Da Nang, Vietnam", category=category, limit=3)
    )
    assert len(result.places) == 1
    assert result.places[0].estimated_visit_cost_vnd is None
    assert result.places[0].fetched_at.tzinfo is not None
    assert result.places[0].types == ["hotel"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_are_sanitized(status):
    provider = LiveProvider(
        "secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text="secret provider detail")),
    )
    with pytest.raises(AgentError) as error:
        await provider.search_places(PlaceSearchRequest(destination="Da Nang"))
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_malformed_record_is_skipped_not_invented():
    provider = LiveProvider(
        "key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"places": [{"id": "broken"}, record()]})
        ),
    )
    result = await provider.search_places(PlaceSearchRequest(destination="Da Nang"))
    assert len(result.places) == 1
    assert any("không hợp lệ" in text for text in result.warnings)


@pytest.mark.asyncio
async def test_empty_search_stays_empty():
    provider = LiveProvider(
        "key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    result = await provider.search_places(PlaceSearchRequest(destination="Nowhere"))
    assert result.places == []


def test_search_timeout_returns_504():
    def handler(request):
        raise httpx.ReadTimeout("provider secret", request=request)

    provider = LiveProvider("key", transport=httpx.MockTransport(handler))
    client = TestClient(create_app(Settings(_env_file=None), provider=provider))
    result = client.post("/api/v1/places/search", json={"destination": "Da Nang"})
    assert result.status_code == 504
    assert "secret" not in result.text


@pytest.mark.asyncio
async def test_details_validate_identity_and_use_header_key():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path.endswith("/real-provider-id")
        assert "key=" not in str(request.url)
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        return httpx.Response(200, json=record())

    provider = LiveProvider("test-key", transport=httpx.MockTransport(handler))
    result = await provider.get_details("real-provider-id")
    assert result.id == "real-provider-id"
    assert result.estimated_visit_cost_vnd is None


@pytest.mark.asyncio
async def test_details_reject_mismatched_id():
    provider = LiveProvider(
        "key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=record()))
    )
    with pytest.raises(AgentError, match="unavailable or invalid"):
        await provider.get_details("different-id")


def test_search_endpoint_auth_validation_and_demo():
    client = TestClient(create_app(Settings(_env_file=None, travelmate_api_token="test")))
    assert client.post("/api/v1/places/search", json={"destination": "Da Nang"}).status_code == 401
    headers = {"Authorization": "Bearer test"}
    assert (
        client.post("/api/v1/places/search", headers=headers, json={"destination": "  "}).status_code == 422
    )
    result = client.post(
        "/api/v1/places/search", headers=headers, json={"destination": "Da Nang", "category": "hotel"}
    )
    assert result.status_code == 200
    assert result.json()["places"][0]["id"] == "demo-hotel"
    assert result.json()["places"][0]["source"] == "fictional_fixture"
