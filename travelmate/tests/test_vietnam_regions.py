import httpx
import pytest
from test_geo_places import feature

from app.geo_places import GeoPlaceService, LocalityChoiceRequired, PublicGeoClient
from app.live_place_agent import LivePlaceAgent, LivePlaceRequest
from app.models import Context
from app.vietnam_regions import load_catalog, polygon_contains


def test_complete_versioned_catalog_and_exact_name_matching():
    catalog = load_catalog()
    assert len(catalog.current) == 34 and len(catalog.regions) == 97
    assert len({r["id"] for r in catalog.regions.values()}) == 97
    assert {r["historical"] for r in catalog.matches("Hà Nội")} == {True, False}
    for query in ["Vĩnh Phúc", "vinh phuc", "Tỉnh Vĩnh Phúc"]:
        matches = catalog.matches(query)
        assert len(matches) == 1 and matches[0]["historical"]
        assert matches[0]["version"] == "2020"
    assert not catalog.matches("Vĩnh Phúc xyz")
    assert not catalog.matches("Cát Bà")
    for region in catalog.current:
        assert region in catalog.matches(region["name"])


def test_polygon_holes_edges_and_multipolygon():
    outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    shape = {"type": "Polygon", "coordinates": [outer, hole]}
    assert polygon_contains(shape, 0.5, 0.5)
    assert polygon_contains(shape, 0, 2)
    assert not polygon_contains(shape, 1.5, 1.5)
    assert not polygon_contains(shape, 5, 2)
    assert polygon_contains({"type": "MultiPolygon", "coordinates": [[outer, hole]]}, 3, 3)


def regional_service(failure=False):
    calls = []
    good = feature()
    good["properties"]["name"] = "Observed hotel in Vinh Yen"
    good["geometry"]["coordinates"] = [105.60, 21.31]
    outside = feature(20)
    outside["geometry"]["coordinates"] = [105.81, 21.04]

    def handler(request):
        calls.append(request)
        if failure and len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [good, outside]})

    return GeoPlaceService(PublicGeoClient(transport=httpx.MockTransport(handler), interval=0)), calls


@pytest.mark.asyncio
async def test_vinh_phuc_no_longer_offers_unrelated_villages_and_filters_polygon():
    geo, calls = regional_service()
    with pytest.raises(LocalityChoiceRequired) as selected:
        await geo.resolve("Vĩnh Phúc")
    choices = selected.value.choices
    assert len(choices) == 1 and choices[0].historical and choices[0].scope == "area"
    assert not calls  # Resolution from the pinned boundary snapshot, no POI/demo data.
    region = await geo.resolve("Vĩnh Phúc", choices[0].id)
    places, metadata, _ = await geo.discover(region, "hotel", 250)
    assert len(places) == 1 and places[0].name == "Observed hotel in Vinh Yen"
    assert metadata[places[0].id].spatial_filter == "reference_polygon"
    assert len(calls) == 4
    assert all("bbox" in request.url.params and "include" in request.url.params for request in calls)
    assert all("radius" not in request.url.params for request in calls)
    assert all(len(request.url.params.get_list("include")) == 1 for request in calls)
    assert all(
        {"osm.tourism.hotel", "osm.tourism.hostel"} <= set(request.url.params["include"].split(","))
        for request in calls
    )


@pytest.mark.asyncio
async def test_historical_id_cannot_be_reused_for_another_province():
    geo, calls = regional_service()
    wrong_id = load_catalog().matches("Vĩnh Phúc")[0]["id"]
    with pytest.raises(LocalityChoiceRequired):
        await geo.resolve("Cà Mau", wrong_id)
    assert not calls


@pytest.mark.asyncio
async def test_partial_grid_error_is_visible_not_silent_success():
    geo, _ = regional_service(failure=True)
    identity = load_catalog().matches("Vĩnh Phúc")[0]["id"]
    report = await LivePlaceAgent(geo_service=geo).run(
        LivePlaceRequest(destination="Vĩnh Phúc", location_id=identity), Context()
    )
    assert report.status == "partial" and len(report.places) == 1
    assert all(m.coverage_partial for m in report.place_metadata.values())
    assert report.resolved_location.historical and report.retrieval_exhaustive is False


@pytest.mark.asyncio
async def test_all_grid_errors_are_source_failure_not_empty_results():
    geo = GeoPlaceService(
        PublicGeoClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)), interval=0)
    )
    identity = load_catalog().matches("Vĩnh Phúc")[0]["id"]
    report = await LivePlaceAgent(geo_service=geo).run(
        LivePlaceRequest(destination="Vĩnh Phúc", location_id=identity), Context()
    )
    assert report.status == "source_error" and not report.places


@pytest.mark.asyncio
async def test_country_query_is_bounded_and_every_result_inside_reference_union():
    geo, calls = regional_service()
    location = await geo.resolve("Việt Nam", search_scope="country")
    places, metadata, _ = await geo.discover(location, "hotel", 250)
    assert location.scope == "country" and len(calls) == 6
    assert len(places) == 2
    assert all(load_catalog().contains("vn:country", p.longitude, p.latitude) for p in places)
    assert all(m.spatial_filter == "reference_polygon" for m in metadata.values())


@pytest.mark.asyncio
async def test_fallback_locality_provider_observed_identity_no_invented_coordinates():
    def handler(request):
        if "open-meteo" in request.url.host:
            return httpx.Response(503)
        f = feature()
        f["properties"].update(name="Specific locality", osm_key="place", osm_value="village")
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [f]})

    geo = GeoPlaceService(PublicGeoClient(transport=httpx.MockTransport(handler), interval=0))
    location = await geo.resolve("Specific locality", search_scope="nearby")
    assert location.id == "photon:node/10" and location.longitude == 107.0482
    with pytest.raises(LocalityChoiceRequired):
        await geo.resolve("Specific locality", "photon:node/999", "nearby")


def test_region_api_serves_metadata_not_geometry_or_fake_pois():
    from fastapi.testclient import TestClient

    from app.live_place_api import LivePlaceSettings, create_app

    with TestClient(create_app(LivePlaceSettings(travelmate_api_token=""))) as client:
        data = client.get("/api/v1/places/regions").json()
        assert len(data["regions"]) == 97
        assert all("geometry" not in p for p in data["regions"])
        assert client.get("/health").json()["coverage"]["poi_exhaustive"] is False


@pytest.mark.asyncio
async def test_unknown_province_area_mode_does_not_guess():
    geo, calls = regional_service()
    with pytest.raises(LocalityChoiceRequired) as result:
        await geo.resolve("Unknown province", search_scope="area")
    assert result.value.choices == [] and not calls
