"""Every catalog region is tested locally; these tests do NOT claim live POI coverage."""

import math

import httpx
import pytest

from app.geo_places import GeoPlaceService, LocalityChoiceRequired, PublicGeoClient
from app.osm_places import normalized
from app.vietnam_regions import load_catalog

REGIONS = list(load_catalog().regions.values())


@pytest.mark.parametrize("region", REGIONS, ids=lambda r: r["id"])
@pytest.mark.asyncio
async def test_each_catalog_region_can_be_found_and_explicitly_selected_without_network(region):
    def forbidden(request):
        pytest.fail("Area resolution must not depend on a live POI or geocoding request")

    geo = GeoPlaceService(PublicGeoClient(transport=httpx.MockTransport(forbidden), interval=0))
    for query in [region["name"], normalized(region["name"])]:
        with pytest.raises(LocalityChoiceRequired) as choices:
            await geo.resolve(query, search_scope="area")
        assert region["id"] in {p.id for p in choices.value.choices}
        location = await geo.resolve(query, region["id"], "area")
        assert location.id == region["id"] and location.boundary_version == region["version"]
        assert location.historical is region["historical"] and location.scope == "area"


@pytest.mark.parametrize("region", REGIONS, ids=lambda r: r["id"])
def test_each_region_geometry_has_finite_closed_rings_inside_its_declared_bbox(region):
    shape = region["geometry"]
    assert shape["type"] in {"Polygon", "MultiPolygon"}
    polygons = shape["coordinates"] if shape["type"] == "MultiPolygon" else [shape["coordinates"]]
    x0, y0, x1, y1 = region["bbox"]
    assert -180 <= x0 < x1 <= 180 and -90 <= y0 < y1 <= 90
    for polygon in polygons:
        assert polygon
        for ring in polygon:
            assert len(ring) >= 4 and ring[0] == ring[-1]
            for lon, lat in ring:
                assert math.isfinite(lon) and math.isfinite(lat)
                assert x0 - 1e-7 <= lon <= x1 + 1e-7 and y0 - 1e-7 <= lat <= y1 + 1e-7
