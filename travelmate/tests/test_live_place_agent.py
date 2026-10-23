from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.browser_places import BrowserPlaceResult, WebSource
from app.live_place_agent import LivePlaceAgent, LivePlaceRequest
from app.models import Context
from app.structured_hotel import parse_hotel

URL = "https://mgallery.accor.com/en/hotels/A5V2.html"


def record():
    import json

    content = {
        "@type": "Hotel",
        "url": URL,
        "name": "Source hotel name",
        "address": {
            "addressLocality": "SAPA",
            "addressCountry": "Vietnam",
            "streetAddress": "Source address",
        },
        "geo": {"latitude": "22.334686", "longitude": "103.840433"},
    }
    return parse_hotel(
        '<script type="application/ld+json">' + json.dumps(content) + "</script>",
        URL,
        "Sa Pa",
        datetime.now(UTC),
    )


def discovery(status="sources_found", places=None, sources=True):
    now = datetime.now(UTC)
    return BrowserPlaceResult(
        status=status,
        query="fixture",
        search_url="https://coccoc.com/search?query=fixture",
        fetched_at=now,
        sources=[
            WebSource(
                id="fixture",
                title="Source result",
                snippet="Untrusted snippet",
                url=URL,
                search_url="https://coccoc.com/search?query=fixture",
                fetched_at=now,
            )
        ]
        if sources
        else [],
        places=[record()] if places is None else places,
    )


class Web:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def run(self, data, context, timeout):
        self.calls.append(data)
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.asyncio
async def test_one_agent_live_contract_grounded_export_and_trace():
    place = record()
    web = Web([discovery(places=[place])])
    result = await LivePlaceAgent(web_tool=web).run(LivePlaceRequest(destination=" Sa   Pa "), Context())
    assert result.status == "success" and result.execution_mode == "tool_workflow"
    assert result.data_origin == "live_network" and result.search_calls == 1
    assert result.places[0] == place and result.places[0].estimated_visit_cost_vnd is None
    assert result.destination == "Sa Pa"
    assert [step.step for step in result.trace] == ["search", "validate", "complete"]
    assert "room_availability" in result.missing_fields


@pytest.mark.asyncio
async def test_keyword_can_broaden_once_and_never_changes_locality():
    web = Web([discovery(places=[]), discovery()])
    result = await LivePlaceAgent(web_tool=web).run(
        LivePlaceRequest(destination="Sa Pa", keyword="quiet"), Context()
    )
    assert result.status == "partial" and result.search_calls == 2
    assert [c.keyword for c in web.calls] == ["quiet", ""]
    assert all(c.destination == "Sa Pa" for c in web.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["blocked", "timeout", "source_error"])
async def test_source_failure_never_returns_demo_or_old_records(status):
    web = Web([discovery(status, places=[], sources=False)])
    result = await LivePlaceAgent(web_tool=web).run(LivePlaceRequest(destination="Sa Pa"), Context())
    assert result.status == status and not result.places
    assert result.trace[-1].step == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["missing_source", "invented_id", "stale", "future", "missing_provenance", "wrong_source"]
)
async def test_invalid_evidence_cannot_be_exported_as_place(fault):
    p = record()
    sources = True
    if fault == "missing_source":
        sources = False
    elif fault == "invented_id":
        p.id = "llm-made-up-id"
    elif fault == "stale":
        p.fetched_at -= timedelta(hours=1)
    elif fault == "future":
        p.fetched_at += timedelta(hours=1)
    elif fault == "missing_provenance":
        p.field_sources.pop("latitude")
    else:
        p.source = "fictional_fixture"
    result = await LivePlaceAgent(web_tool=Web([discovery(places=[p], sources=sources)])).run(
        LivePlaceRequest(destination="Sa Pa"), Context()
    )
    assert result.status == "source_error" and not result.places


@pytest.mark.asyncio
async def test_no_cross_request_place_memory_and_needs_not_claimed_verified():
    web = Web([discovery(), discovery(places=[])])
    agent = LivePlaceAgent(web_tool=web)
    first = await agent.run(LivePlaceRequest(destination="Sa Pa", needs="gia đình"), Context())
    second = await agent.run(LivePlaceRequest(destination="Sa Pa"), Context())
    assert first.status == "partial" and not first.requirements_verified
    assert second.status == "source_error" and not second.places


@pytest.mark.asyncio
async def test_adk_engine_search_details_and_repaired_selection_use_real_tools_contract():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    p = record()

    class Reader:
        async def read(self, url, destination):
            assert url == URL and destination == "Sa Pa"
            return record()

    model = ScriptedModel(
        calls=[
            {"name": "search_places", "args": {"keyword": ""}},
            {"name": "get_place_details", "args": {"place_id": p.id}},
            {"name": "submit_places", "args": {"place_ids": ["invented"]}},
            {"name": "submit_places", "args": {"place_ids": [p.id]}},
        ]
    )
    result = await LivePlaceAgent(
        model_factory=lambda: model, web_tool=Web([discovery()]), reader=Reader()
    ).run(LivePlaceRequest(destination="Sa Pa"), Context())
    assert result.status == "success" and result.execution_mode == "adk_llm"
    assert result.search_calls == result.detail_calls == 1
    assert result.places[0].source_url == URL
    assert any(o.get("accepted") is False for o in model.observations)


@pytest.mark.asyncio
async def test_unexpected_tool_failure_has_sanitized_output():
    result = await LivePlaceAgent(web_tool=Web([RuntimeError("private-text-not-for-output")])).run(
        LivePlaceRequest(destination="Sa Pa"), Context()
    )
    assert result.status == "source_error" and "private-text-not-for-output" not in result.model_dump_json()


@pytest.mark.parametrize(
    "value",
    [
        {"destination": "  "},
        {"destination": "Sa Pa", "category": "flight"},
        {"destination": "Sa Pa", "limit": True},
    ],
)
def test_input_rejects_unsupported_or_ambiguous_contract(value):
    with pytest.raises(ValidationError):
        LivePlaceRequest.model_validate(value)


def test_ui_api_status_auth_origin_and_failed_sources():
    from fastapi.testclient import TestClient

    from app.live_place_api import LivePlaceSettings, create_app

    web = Web([discovery(), discovery("blocked", places=[], sources=False)])
    app = create_app(LivePlaceSettings(travelmate_api_token="local-test"), LivePlaceAgent(web_tool=web))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/health").json()["mode"] == "tool_workflow"
        path, payload = "/api/v1/places/live", {"destination": "Sa Pa"}
        assert client.post(path, json=payload).status_code == 401
        headers = {"Authorization": "Bearer local-test"}
        assert (
            client.post(path, json=payload, headers={**headers, "Origin": "https://example.com"}).status_code
            == 403
        )
        result = client.post(path, json=payload, headers=headers)
        assert result.status_code == 200 and result.json()["status"] == "success"
        assert client.get("/health").json()["last_success_at"]
        result = client.post(path, json=payload, headers=headers)
        assert result.status_code == 503 and result.json()["status"] == "blocked"
        assert not result.json()["places"]
        assert (
            client.post(
                path, json={"destination": "Sa Pa", "category": "flight"}, headers=headers
            ).status_code
            == 422
        )


def test_adk_configuration_cannot_silently_switch_to_workflow():
    from app.live_place_api import LivePlaceSettings, create_app

    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        create_app(LivePlaceSettings(live_place_mode="adk_llm", google_api_key=""))
