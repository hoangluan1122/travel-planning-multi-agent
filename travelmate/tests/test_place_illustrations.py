"""Every searched place gets an image: its own photo, or a labelled, credited illustration of its kind."""

import httpx
import pytest

from app.core.models import Place
from app.tools.places.place_media import (
    KIND_RULES,
    WikipediaImages,
    illustrate,
    illustration_table,
    kind_for,
    kind_illustration,
)


def place(name, types=(), ident=None):
    return Place(id=ident or name, name=name, address="a", latitude=16, longitude=107, source="osm", types=list(types))


def test_every_kind_has_a_credited_wikimedia_illustration():
    table = illustration_table()
    needed = {kind for kind, _, _ in KIND_RULES} | {"food", "cafe", "sight"}
    assert needed <= set(table)
    for kind, entry in table.items():
        assert entry["label"] and entry["photos"], kind
        for photo in entry["photos"]:
            assert photo["url"].startswith("https://upload.wikimedia.org/wikipedia/commons/"), kind
            assert photo["source_url"].startswith("https://commons.wikimedia.org/wiki/File:"), kind
            assert photo["author"].strip() and photo["license"], kind


@pytest.mark.parametrize("name,types,kind", [
    ("Chùa Thiên Mụ", ["attraction"], "pagoda"),
    ("Đền Ngọc Sơn", [], "temple"),
    ("Hội quán Phúc Kiến", ["attraction"], "temple"),
    ("Lăng Tự Đức", ["tomb"], "tomb"),
    ("Bảo tàng Cổ vật Cung đình", ["museum"], "museum"),  # "đình" inside a name is not a communal house
    ("Đình Kim Liên", [], "communal_house"),
    ("Bảo tàng Hồ Chí Minh", [], "museum"),
    ("Tượng đài Hồ Chí Minh", [], "monument"),           # "Hồ Chí Minh" is not a lake
    ("Hồ Hoàn Kiếm", [], "lake"),
    ("Chợ Đông Ba", [], "market"),
    ("Bãi biển Mỹ Khê", [], "beach"),
    ("Thác Datanla", [], "waterfall"),
    ("Hang Sơn Đoòng", [], "cave"),
    ("Đèo Hải Vân", [], "viewpoint"),
    ("Cầu Rồng", [], "bridge"),
    ("Thảo Cầm Viên", [], "zoo"),
    ("Cù Lao Chàm", [], "island"),
    ("Phố cổ Hội An", [], "old_quarter"),
    ("Dinh Độc Lập", ["attraction"], "sight"),
    ("Kim Hotel", ["hotel"], "hotel"),
    ("Mai Châu Homestay", ["guest_house"], "homestay"),
    ("An Lâm Resort", ["resort"], "resort"),
    ("Chùa View Hotel", ["hotel"], "hotel"),               # a stay stays a stay, whatever its name says
    ("Bún bò Huế Kim Đồng", ["restaurant"], "food"),
    ("Cộng Cà Phê", ["cafe"], "cafe"),
])
def test_kind_from_name_then_type(name, types, kind):
    assert kind_for(place(name, types)) == kind


def test_illustration_is_labelled_and_credited_never_presented_as_the_place():
    photo = kind_illustration(place("Kim Hotel", ["hotel"]))
    chosen = next(p for p in illustration_table()["hotel"]["photos"] if p["url"] == photo.url)
    assert photo.illustration and photo.source_url == chosen["source_url"]
    assert photo.attribution.startswith("Ảnh minh hoạ phòng khách sạn, không phải ảnh của nơi này")
    assert chosen["author"] in photo.attribution and chosen["license"] in photo.attribution


def test_same_place_same_illustration_and_a_list_is_not_one_picture():
    hotels = [place(f"Khách sạn {i}", ["hotel"], ident=f"h{i}") for i in range(12)]
    first = [kind_illustration(h).url for h in hotels]
    assert first == [kind_illustration(h).url for h in hotels]  # stable per place
    assert len(set(first)) == len(illustration_table()["hotel"]["photos"]) > 1


def test_illustrate_keeps_real_photos_and_fills_the_rest():
    own = kind_illustration(place("x")).model_copy(update={"illustration": False, "url": "https://upload.wikimedia.org/own.jpg"})
    with_photo = place("Đại Nội").model_copy(update={"photo": own})
    out = illustrate([with_photo, place("Chợ Đông Ba")])
    assert out[0].photo.url == "https://upload.wikimedia.org/own.jpg" and not out[0].photo.illustration
    assert out[1].photo.illustration and out[1].photo.url in {x["url"] for x in illustration_table()["market"]["photos"]}


@pytest.mark.asyncio
async def test_every_place_has_an_image_when_sources_fail_or_past_the_limit():
    """Wikimedia down and more places than the lookup limit: still one image per place, all labelled."""
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    places = [place(f"Khách sạn {i}", ["hotel"], ident=f"h{i}") for i in range(5)] + [place("Thác Pongour")]
    out = await WikipediaImages(transport=transport, limit=2).enrich(places)
    assert len(out) == 6 and all(p.photo is not None and p.photo.illustration for p in out)
    assert out[-1].photo.url in {x["url"] for x in illustration_table()["waterfall"]["photos"]}
