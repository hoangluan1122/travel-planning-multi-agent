"""Regression contracts for real-world resolver failures found in the audit."""

import json
from pathlib import Path

import httpx
import pytest
from test_geo_places import feature, locality

from app.geo_places import GeoPlaceService, LocalityChoiceRequired, PublicGeoClient, relevant_name
from app.live_place_agent import LivePlaceAgent, LivePlaceRequest
from app.models import Context
from app.osm_places import normalized


def source(geonames, photon, *, photon_status=200):
    def handler(request):
        if "open-meteo" in request.url.host:
            return httpx.Response(200, json={"results": geonames})
        return httpx.Response(photon_status, json={"type": "FeatureCollection", "features": photon})

    return GeoPlaceService(PublicGeoClient(transport=httpx.MockTransport(handler), interval=0))


def landmark(name, key, value, identity=77):
    item = feature(identity)
    item["properties"].update(name=name, osm_key=key, osm_value=value, state="Ninh Bình")
    return item


@pytest.mark.asyncio
async def test_exact_geonames_village_cannot_hide_conflicting_landmark():
    geo = source([locality(name="Tràng An")], [landmark("Khu du lịch Tràng An", "tourism", "attraction")])
    with pytest.raises(LocalityChoiceRequired) as result:
        await geo.resolve("Tràng An", search_scope="nearby")
    assert {p.id for p in result.value.choices} == {"geonames:1", "photon:node/77"}
    chosen = await geo.resolve("Tràng An", "photon:node/77", "nearby")
    assert chosen.name == "Khu du lịch Tràng An"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [
        ("boundary", "national_park"),
        ("leisure", "nature_reserve"),
        ("natural", "peak"),
        ("aerialway", "station"),
    ],
)
async def test_landmark_roles_are_available_for_explicit_selection(key, value):
    geo = source([], [landmark("Địa danh thử", key, value)])
    selected = await geo.resolve("Địa danh thử", search_scope="nearby")
    assert selected.feature_code == "OSM:" + value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [("tourism", "hotel"), ("tourism", "information"), ("amenity", "restaurant"), ("highway", "bus_stop")],
)
async def test_same_name_business_or_bus_stop_is_not_a_destination(key, value):
    geo = source([], [landmark("Fansipan", key, value)])
    with pytest.raises(LocalityChoiceRequired) as result:
        await geo.resolve("Fansipan", search_scope="nearby")
    assert not result.value.choices


@pytest.mark.asyncio
async def test_photon_qualifier_cannot_leak_to_wrong_province():
    geo = source([], [landmark("Tràng An", "tourism", "attraction")])
    with pytest.raises(LocalityChoiceRequired) as result:
        await geo.resolve("Tràng An, Bắc Ninh", search_scope="nearby")
    assert not result.value.choices


@pytest.mark.asyncio
async def test_crosscheck_outage_requires_confirmation_not_false_confidence():
    geo = source([locality()], [], photon_status=503)
    with pytest.raises(LocalityChoiceRequired) as result:
        await geo.resolve("Cát Bà", search_scope="nearby")
    assert result.value.choices[0].id == "geonames:1"
    assert (await geo.resolve("Cát Bà", "geonames:1", "nearby")).id == "geonames:1"


def test_unicode_name_normalization_and_noise_filter():
    assert normalized("Ðà Lạt") == normalized("Đà Lạt") == normalized("Da Lat")
    assert relevant_name("Fansipan", "Đinh Núi Phan Xi Phăng")
    assert relevant_name("Bà Nà Hills", "Sun World Bà Nà Hills")
    assert not relevant_name("Đà Lạt", "Đã Tịch")
    assert not relevant_name("Tràng An", "An Viên Beach")


@pytest.mark.asyncio
async def test_area_centroid_is_explicit_not_claimed_as_entrance():
    item = landmark("Vườn quốc gia Cúc Phương", "boundary", "national_park")
    item["properties"]["osm_type"] = "R"
    geo = source([], [item])
    selected = await geo.resolve("Vườn quốc gia Cúc Phương", search_scope="nearby")
    assert selected.coordinate_kind == "geometry_center"


@pytest.mark.asyncio
async def test_recorded_real_cuc_phuong_payload_survives_resolver_filter():
    # Frozen actual HTTP evidence, used offline only; never a production fallback.
    path = Path(__file__).parent / "fixtures/cuc_phuong_photon.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    geo = source([], payload["features"])
    choices = await geo.resolve_photon("Vườn quốc gia Cúc Phương")
    assert choices and all(p.name == "Vườn quốc gia Cúc Phương" for p in choices)
    assert any(p.feature_code in {"OSM:national_park", "OSM:nature_reserve"} for p in choices)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "radius,offset,suggested", [(3000, 0, 5000), (5000, 0, 10000), (10000, 0, None), (5000, 5, None)]
)
async def test_empty_source_offers_explicit_expansion_without_changing_radius(radius, offset, suggested):
    geo = source([locality()], [])
    report = await LivePlaceAgent(geo_service=geo).run(
        LivePlaceRequest(destination="Cát Bà", radius_m=radius, offset=offset), Context()
    )
    assert report.status == "no_results" and not report.places
    assert report.applied_radius_m == radius and report.suggested_radius_m == suggested
