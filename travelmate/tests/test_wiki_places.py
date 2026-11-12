"""Wikipedia sights: the fallback place source when Photon/OpenStreetMap is down."""

from datetime import UTC, datetime

import httpx
import pytest

from app.tools.places.geo_places import Locality
from app.tools.places.wiki_places import WikipediaPlaces, sight_type

HUE = Locality(id="geonames:1", name="Huế", latitude=16.4637, longitude=107.5909, feature_code="PPLA",
               source_url="https://example.test", fetched_at=datetime.now(UTC))


def page(pageid, title, lat=16.47, lon=107.58, description="", thumb=None):
    item = {"pageid": pageid, "title": title, "coordinates": [{"lat": lat, "lon": lon}],
            "fullurl": f"https://vi.wikipedia.org/wiki/{pageid}", "description": description}
    if thumb:
        item["thumbnail"] = {"source": thumb}
    return item


@pytest.mark.parametrize("title,kind", [
    ("Lăng Tự Đức", "tomb"), ("Chùa Thiên Mụ", "temple"), ("Bảo tàng Cổ vật Cung đình Huế", "museum"),
    ("Phu Văn lâu", "castle"), ("Kỳ đài (Huế)", "monument"), ("Chợ Đông Ba", "attraction"),
    ("Phú Xuân (quận)", None), ("Trận Mậu Thân tại Huế", None), ("Vĩnh Long", None), ("Đồng Hới", None),
    ("Điện Biên Phủ", None), ("Câu lạc bộ bóng đá Huế", None), ("Lăng", None),
])
def test_only_titles_that_name_a_sight_are_kept(title, kind):
    assert sight_type(title) == kind


@pytest.mark.asyncio
async def test_nearby_keeps_sights_drops_wards_and_parts_of_listed_sites_photo_first():
    pages = [
        page(1, "Hoàng thành Huế", 16.469, 107.578),
        page(2, "Ngọ Môn (Hoàng thành Huế)", 16.467, 107.579, thumb="https://upload.wikimedia.org/a.jpg"),
        page(3, "Chùa Thiên Mụ", 16.453, 107.545, "ngôi chùa ở Huế", thumb="https://upload.wikimedia.org/b.jpg"),
        page(4, "Hương Thủy (phường)", description="phường thuộc thành phố Huế"),
        page(5, "Chợ Hương Sơ", description="phường thuộc thành phố Huế"),
        page(6, "Kỳ đài (Huế)", 16.466, 107.580),
        {"pageid": 7, "title": "Lăng không có toạ độ"},
    ]
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"query": {"pages": pages}})

    places = await WikipediaPlaces(transport=httpx.MockTransport(handler)).nearby(HUE, 15000)
    assert [p.name for p in places] == ["Chùa Thiên Mụ", "Kỳ đài", "Hoàng thành Huế"]
    assert places[0].photo and places[0].photo.url.endswith("b.jpg")
    assert places[0].id == "wikipedia:vi/3" and places[0].source == "wikipedia"
    assert seen["ggsradius"] == "10000"  # the API limit


@pytest.mark.asyncio
async def test_a_wikipedia_failure_is_an_empty_list_not_an_error():
    def handler(request):
        return httpx.Response(503)

    assert await WikipediaPlaces(transport=httpx.MockTransport(handler)).nearby(HUE, 5000) == []
