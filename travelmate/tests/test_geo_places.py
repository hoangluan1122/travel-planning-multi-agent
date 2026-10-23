from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from app.agents import AgentError
from app.geo_places import GeoPlaceService, LocalityChoiceRequired, PublicGeoClient
from app.live_place_agent import GeoGroundedProvider, LivePlaceAgent, LivePlaceRequest
from app.models import Context, PlaceSearchRequest


def locality(identity=1, name="Cát Bà", **extra):
    return dict(
        id=identity,
        name=name,
        latitude=20.72779,
        longitude=107.04819,
        country_code="VN",
        feature_code="PPL",
        admin1="Hải Phòng",
        **extra,
    )


def feature(identity=10, category="hotel", **props):
    return dict(
        type="Feature",
        properties=dict(
            name=f"Source place {identity}",
            osm_type="N",
            osm_id=identity,
            osm_key="amenity" if category == "restaurant" else "tourism",
            osm_value=category,
            countrycode="VN",
            street="Source street",
            city="Source locality",
            **props,
        ),
        geometry=dict(type="Point", coordinates=[107.0482, 20.728]),
    )


def service(locations=None, features=None, status=200):
    calls = []

    def handler(request):
        calls.append(request)
        payload = (
            {"results": locations if locations is not None else [locality()]}
            if "open-meteo" in request.url.host
            else {
                "type": "FeatureCollection",
                "features": []
                if request.url.path == "/api/" and "include" in request.url.params
                else features
                if features is not None
                else [feature(i) for i in range(10, 18)],
            }
        )
        return httpx.Response(status, json=payload)

    return GeoPlaceService(PublicGeoClient(transport=httpx.MockTransport(handler), interval=0)), calls


@pytest.mark.asyncio
async def test_real_source_shape_multiple_results_pagination_cache_and_provenance():
    geo, calls = service()
    agent = LivePlaceAgent(geo_service=geo)
    a = await agent.run(LivePlaceRequest(destination="Cát Bà", limit=5), Context())
    b = await agent.run(LivePlaceRequest(destination="Cát Bà", limit=5, offset=5), Context())
    assert a.status == b.status == "success"
    assert len(a.places) == 5 and len(b.places) == 3 and a.has_more and not b.has_more
    assert a.candidate_count == 8 and len(calls) == 3
    assert not set(p.id for p in a.places) & set(p.id for p in b.places)
    assert all(m.cache_hit for m in b.place_metadata.values())
    assert a.places[0].fetched_at == b.places[0].fetched_at
    for p in a.places:
        assert p.field_sources["latitude"] == p.source_url
        assert p.source_url.endswith(p.id.removeprefix("osm:"))
        assert p.estimated_visit_cost_vnd is None and p.image_reference is None
        assert (p.latitude, p.longitude) != (a.resolved_location.latitude, a.resolved_location.longitude)


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["hotel", "restaurant", "attraction"])
async def test_all_categories_use_actual_source_tags(category):
    geo, calls = service(features=[feature(category=category)])
    report = await LivePlaceAgent(geo_service=geo).run(
        LivePlaceRequest(destination="Cát Bà", category=category), Context()
    )
    assert report.category == category and len(report.places) == 1
    poi_calls = [c for c in calls if c.url.path == "/reverse"]
    assert len(poi_calls) == 1 and category in str(poi_calls[0].url)


@pytest.mark.asyncio
async def test_ambiguity_requires_explicit_choice_and_rejects_arbitrary_id():
    geo, calls = service(locations=[locality(), locality(2)])
    agent = LivePlaceAgent(geo_service=geo)
    report = await agent.run(LivePlaceRequest(destination="Cát Bà"), Context())
    assert report.status == "needs_location" and len(report.location_options) == 2 and not report.places
    assert len(calls) == 2
    report = await agent.run(LivePlaceRequest(destination="Cát Bà", location_id="geonames:99"), Context())
    assert report.status == "needs_location"
    report = await agent.run(LivePlaceRequest(destination="Cát Bà", location_id="geonames:2"), Context())
    assert report.resolved_location.id == "geonames:2" and report.status == "success"


@pytest.mark.asyncio
async def test_wrong_country_province_and_unknown_names_never_silently_choose():
    for raw in [
        [{**locality(), "country_code": "US"}],
        [locality(name="Different")],
        [{**locality(), "feature_code": "ADM1"}],
        [],
    ]:
        geo, _ = service(locations=raw)
        with pytest.raises(LocalityChoiceRequired):
            await geo.resolve("Cát Bà")


@pytest.mark.asyncio
async def test_invalid_unrelated_unnamed_duplicate_and_far_features_excluded():
    values = [feature(), feature(), feature(11, category="restaurant")]
    for key, value in [("name", ""), ("countrycode", "US"), ("osm_id", True), ("osm_type", "invalid")]:
        f = feature(12)
        f["properties"][key] = value
        values.append(f)
    for coords in [[0, 0], [True, 20], [999, 999], [107, float("nan")]]:
        f = feature(13)
        f["geometry"]["coordinates"] = coords
        values.append(f)
    # Direct parse for NaN since JSON transport correctly rejects non-JSON numbers.
    geo, _ = service(features=values[:-1])
    loc = await geo.resolve("Cát Bà")
    with pytest.raises(ValueError):
        geo.parse_feature(values[-1], "hotel", loc, 3000, datetime.now(UTC), False, "source")
    places, _, _ = await geo.discover(loc, "hotel", 3000)
    assert len(places) == 1 and places[0].id == "osm:node/10"


@pytest.mark.asyncio
async def test_way_is_centroid_and_missing_address_not_invented():
    f = feature()
    f["properties"] = {k: v for k, v in f["properties"].items() if k not in {"street", "city"}}
    f["properties"]["osm_type"] = "W"
    geo, _ = service(features=[f])
    loc = await geo.resolve("Cát Bà")
    places, metadata, _ = await geo.discover(loc, "hotel", 3000)
    assert places[0].coordinate_kind == "geometry_center" and places[0].address == ""
    assert "address" not in places[0].field_sources
    assert metadata[places[0].id].address_precision == "missing"


@pytest.mark.asyncio
async def test_valid_empty_different_from_source_failure_and_keyword_broadening():
    geo, _ = service(features=[])
    result = await LivePlaceAgent(geo_service=geo).run(
        LivePlaceRequest(destination="Cát Bà", keyword="missing"), Context()
    )
    assert result.status == "no_results" and result.search_calls == 2
    geo, _ = service(status=503)
    result = await LivePlaceAgent(geo_service=geo).run(LivePlaceRequest(destination="Cát Bà"), Context())
    assert result.status == "source_error" and not result.places


@pytest.mark.asyncio
async def test_output_tampering_fixed_locality_and_call_budget():
    geo, _ = service()
    provider = GeoGroundedProvider(LivePlaceRequest(destination="Cát Bà"), geo)
    result = await provider.search_places(PlaceSearchRequest(destination="Cát Bà", category="hotel"))
    raw = deepcopy(result.places[0])
    raw.latitude = 0
    with pytest.raises(AgentError):
        provider.validate_record(raw)
    with pytest.raises(AgentError):
        await provider.search_places(PlaceSearchRequest(destination="Sa Pa", category="hotel"))
    with pytest.raises(AgentError):
        await provider.search_places(PlaceSearchRequest(destination="Cát Bà", category="restaurant"))
    with pytest.raises(AgentError):
        await provider.get_details("invented")
    with pytest.raises(AgentError):
        await provider.search_places(PlaceSearchRequest(destination="Cát Bà", category="hotel"))


@pytest.mark.asyncio
async def test_rate_limit_cooldown_preserves_failure_no_cache():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(429, json={"error": True})

    client = PublicGeoClient(transport=httpx.MockTransport(handler), interval=0)
    for _ in range(2):
        with pytest.raises(AgentError):
            await client.get("https://photon.komoot.io/reverse", [])
    assert count == 1


@pytest.mark.asyncio
async def test_malformed_individual_features_do_not_break_good_records():
    bad = feature(99)
    bad["properties"]["countrycode"] = 1
    geo, _ = service(features=[None, {"properties": [], "geometry": {}}, bad, feature()])
    loc = await geo.resolve("Cát Bà")
    places, _, skipped = await geo.discover(loc, "hotel", 3000)
    assert len(places) == 1 and skipped == 2


@pytest.mark.asyncio
async def test_adk_geo_tools_reject_fabricated_output_and_submit_observed_ids():
    pytest.importorskip("google.adk")
    from test_adk_tools import ScriptedModel

    geo, _ = service(features=[feature()])
    model = ScriptedModel(
        calls=[
            {"name": "search_places", "args": {"keyword": ""}},
            {"name": "get_place_details", "args": {"place_id": "osm:node/10"}},
            {"name": "submit_places", "args": {"place_ids": ["made-up"]}},
            {"name": "submit_places", "args": {"place_ids": ["osm:node/10"]}},
        ]
    )
    result = await LivePlaceAgent(geo_service=geo, model_factory=lambda: model).run(
        LivePlaceRequest(destination="Cát Bà"), Context()
    )
    assert result.status == "success" and result.execution_mode == "adk_llm"
    assert result.search_calls == result.detail_calls == 1
    assert result.places[0].source == "osm_photon"
    assert any(o.get("accepted") is False for o in model.observations)


def test_api_location_choice_and_empty_are_normal_200_responses():
    from fastapi.testclient import TestClient

    from app.live_place_api import LivePlaceSettings, create_app

    geo, _ = service(locations=[locality(), locality(2)], features=[])
    with TestClient(
        create_app(LivePlaceSettings(travelmate_api_token=""), LivePlaceAgent(geo_service=geo))
    ) as client:
        result = client.post("/api/v1/places/live", json={"destination": "Cát Bà"})
        assert result.status_code == 200 and result.json()["status"] == "needs_location"
        result = client.post(
            "/api/v1/places/live", json={"destination": "Cát Bà", "location_id": "geonames:1"}
        )
        assert result.status_code == 200 and result.json()["status"] == "no_results"
