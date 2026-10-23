import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from app.agents import AgentError
from app.models import Context, PlaceSearchRequest
from app.osm_places import OSMPlaceProvider, OSMSearchTool
from app.place_locations import LocationChoiceRequired


def locality(identity=1, name="Sa Pa"):
    return {
        "type": "node",
        "id": identity,
        "lat": 22.34,
        "lon": 103.84,
        "tags": {"name": name, "place": "town"},
    }


def poi(identity=2, **tags):
    return {
        "type": "node",
        "id": identity,
        "lat": 22.3401,
        "lon": 103.8401,
        "tags": {"name": "Khách sạn thử nghiệm", "tourism": "hotel", **tags},
    }


def provider(locations=None, places=None, detail=None):
    calls = []

    def handler(request):
        query = parse_qs(request.content.decode())["data"][0]
        calls.append(query)
        assert '["ISO3166-1"="VN"]' in query
        assert request.headers["user-agent"].startswith("TravelMate")
        if '"place"~' in query:
            elements = locations if locations is not None else [locality()]
        elif "around:" in query:
            elements = places if places is not None else [poi()]
        else:
            elements = detail if detail is not None else [poi()]
        return httpx.Response(200, json={"elements": elements})

    return OSMPlaceProvider(transport=httpx.MockTransport(handler), min_interval=0), calls


@pytest.mark.asyncio
async def test_search_provenance_and_unknown_prices():
    agent, calls = provider(
        places=[
            poi(
                opening_hours="Mo-Su 08:00-22:00",
                website="https://example.org",
                image="File:Sample.jpg",
                **{"addr:street": "Đường thử nghiệm"},
            )
        ]
    )
    result = await agent.search_places(PlaceSearchRequest(destination="Sa Pa", category="hotel"))
    place = result.places[0]
    assert place.id == "osm:node/2" and place.estimated_visit_cost_vnd is None
    assert place.source_url == "https://www.openstreetmap.org/node/2"
    assert place.opening_hours_raw == "Mo-Su 08:00-22:00"
    assert place.image_reference == "File:Sample.jpg"
    assert place.field_sources["website_url"] == place.source_url
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ambiguous_location_requires_choice_and_not_first_result():
    source, calls = provider(locations=[locality(1), locality(3)])
    query = PlaceSearchRequest(destination="Sa Pa")
    with pytest.raises(LocationChoiceRequired) as error:
        await source.search_places(query)
    assert len(error.value.candidates) == 2 and len(calls) == 1
    result = await source.search_places(query.model_copy(update={"location_id": "osm:node/3"}))
    assert result.places and len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_selected_location_cannot_bypass_resolution():
    source, calls = provider()
    with pytest.raises(LocationChoiceRequired):
        await source.search_places(PlaceSearchRequest(destination="Sa Pa", location_id="osm:node/999"))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_locality_is_clarification_not_no_pois():
    source, calls = provider(locations=[])
    result = await OSMSearchTool(source).run(PlaceSearchRequest(destination="Unknown"), Context())
    assert result.status == "needs_location" and not result.places and len(calls) == 1


@pytest.mark.asyncio
async def test_cache_coalesces_concurrent_queries_and_retains_fetch_time():
    source, calls = provider()
    query = PlaceSearchRequest(destination="Sa Pa")
    a, b = await asyncio.gather(source.search_places(query), source.search_places(query))
    assert len(calls) == 2
    assert a.places[0].fetched_at == b.places[0].fetched_at


@pytest.mark.asyncio
async def test_duplicate_and_outside_radius_records_removed():
    same = poi(4)
    distant = poi(5)
    distant["lat"] = 21
    source, _ = provider(places=[poi(), poi(), same, distant])
    result = await source.search_places(PlaceSearchRequest(destination="Sa Pa"))
    assert len(result.places) == 1


@pytest.mark.asyncio
async def test_way_center_is_labelled_not_entrance():
    way = poi()
    way.update(type="way", center={"lat": way.pop("lat"), "lon": way.pop("lon")})
    source, _ = provider(places=[way])
    result = await source.search_places(PlaceSearchRequest(destination="Sa Pa"))
    assert result.places[0].coordinate_kind == "geometry_center"


@pytest.mark.asyncio
async def test_all_corrupt_records_not_reported_as_no_results():
    source, _ = provider(places=[{"id": 2}])
    with pytest.raises(AgentError):
        await source.search_places(PlaceSearchRequest(destination="Sa Pa"))


@pytest.mark.asyncio
async def test_unsafe_website_omitted_and_address_not_invented():
    source, _ = provider(places=[poi(website="javascript:alert(1)")])
    result = await source.search_places(PlaceSearchRequest(destination="Sa Pa"))
    assert result.places[0].website_url is None and result.places[0].address == ""


@pytest.mark.asyncio
async def test_detail_id_validation_and_mismatched_response():
    source, calls = provider()
    with pytest.raises(AgentError):
        await source.get_details("osm:node/2);out;")
    assert not calls
    with pytest.raises(AgentError):
        await source.get_details("osm:node/3")


@pytest.mark.asyncio
async def test_ql_user_text_is_escaped():
    source, calls = provider(locations=[])
    await source.resolve_locations('X");out;node(1);("')
    assert '\\"' in calls[0]
    assert calls[0].endswith(");out body 11;")


@pytest.mark.asyncio
async def test_overpass_partial_result_fails_closed():
    source = OSMPlaceProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"elements": [locality()], "remark": "runtime timeout"})
        )
    )
    with pytest.raises(AgentError):
        await source.resolve_locations("Sa Pa")


@pytest.mark.asyncio
async def test_rate_limit_response_enforces_cooldown_no_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    source = OSMPlaceProvider(transport=httpx.MockTransport(handler), min_interval=0)
    for _ in range(2):
        with pytest.raises(AgentError):
            await source.resolve_locations("Sa Pa")
    assert len(calls) == 1


def test_place_api_no_longer_requires_maps_for_osm():
    from app.place_api import PlaceSettings, create_app

    app = create_app(
        PlaceSettings(
            _env_file=None,
            travelmate_api_token="test",
            google_api_key="test",
            google_maps_api_key="",
            place_provider="osm",
        )
    )
    assert app.title


@pytest.mark.asyncio
async def test_real_adk_tools_use_osm_records_without_rewriting_them():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    from app.place_agent import PlaceAgentInput, PlaceAssistant

    source, calls = provider()
    agent = PlaceAssistant(
        lambda: ScriptedModel(
            calls=[
                {"name": "search_places", "args": {"keyword": ""}},
                {"name": "get_place_details", "args": {"place_id": "osm:node/2"}},
                {"name": "submit_places", "args": {"place_ids": ["osm:node/2"]}},
            ]
        ),
        source,
    )
    result = await agent.run(PlaceAgentInput(destination="Sa Pa", category="hotel"), Context())
    assert result.status == "candidates"
    assert result.places[0].source_url == "https://www.openstreetmap.org/node/2"
    assert result.places[0].estimated_visit_cost_vnd is None
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_adk_stops_for_locality_choice_instead_of_guessing():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    from app.place_agent import PlaceAgentInput, PlaceAssistant

    source, calls = provider(locations=[locality(1), locality(3)])
    model = ScriptedModel(calls=[{"name": "search_places", "args": {"keyword": ""}}])
    result = await PlaceAssistant(lambda: model, source).run(PlaceAgentInput(destination="Sa Pa"), Context())
    assert result.status == "needs_location" and len(result.location_options) == 2
    assert result.places == [] and model.index == 1 and len(calls) == 1


def test_place_tools_api_does_not_need_gemini_or_maps():
    from fastapi.testclient import TestClient

    from app.osm_places import OSMLocationTool
    from app.specialist_api import SpecialistSettings, create_app

    source, _ = provider()
    app = create_app(
        SpecialistSettings(_env_file=None, travelmate_api_token="token", google_api_key=""),
        {"osm_locations": OSMLocationTool(source), "osm_places": OSMSearchTool(source)},
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer token"}
        path = "/api/v1/tools/places/search"
        assert client.post(path, json={"destination": "Sa Pa"}).status_code == 401
        assert (
            client.post(path, headers=headers, json={"destination": "Sa Pa"}).json()["status"] == "candidates"
        )
        resolved = client.post(
            "/api/v1/tools/places/locations", headers=headers, json={"destination": "Sa Pa"}
        )
        assert resolved.json()["candidates"][0]["id"] == "osm:node/1"
