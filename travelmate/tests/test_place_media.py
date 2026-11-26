"""Wikipedia photos only when the article clearly is the place; Google photos only via allowlist."""

import httpx
import pytest

from app.core.models import Place
from app.tools.places.place_media import GooglePhotoProxy, WikipediaImages, dish_for, titles_match


def stand_in(photo):
    """A labelled illustration of the place's kind: what enrich gives when no photo matches."""
    return photo is not None and photo.illustration and "không phải ảnh của nơi này" in photo.attribution


def place(ident, name, types=("tomb",)):
    return Place(id=ident, name=name, address="a", latitude=16, longitude=107, source="osm", types=list(types))


def wiki_transport(pages_by_query, calls):
    def handler(request):
        query = request.url.params["gsrsearch"]
        calls.append(query)
        title, thumb = pages_by_query.get(query, (None, None))
        pages = [] if title is None else [{"title": title, "fullurl": "https://vi.wikipedia.org/wiki/X",
                                           "thumbnail": {"source": thumb}}]
        return httpx.Response(200, json={"query": {"pages": pages}})

    return httpx.MockTransport(handler)


def test_titles_match_ignores_case_and_diacritics_but_not_other_places():
    assert titles_match("Lăng Tự Đức", "lăng tu duc")
    assert titles_match("Điện Thái Hòa", "Điện Thái Hòa (Hoàng thành Huế)")
    assert not titles_match("Crazy House", "Biệt thự Hằng Nga")


@pytest.mark.asyncio
async def test_enrich_adds_matching_wikimedia_photos_only():
    calls = []
    transport = wiki_transport(
        {
            "Lăng Tự Đức": ("Lăng Tự Đức", "https://thumb.wikimedia.org/a.jpg"),
            "Crazy House": ("Biệt thự Hằng Nga", "https://thumb.wikimedia.org/b.jpg"),  # different title
            "Lăng X": ("Lăng X", "https://evil.example/x.jpg"),  # not a Wikimedia host
        },
        calls,
    )
    places = [
        place("t", "Lăng Tự Đức"), place("c", "Crazy House", ["museum"]), place("x", "Lăng X"),
        place("r", "Quán Bún", ["restaurant"]),
    ]
    out = await WikipediaImages(transport=transport).enrich(places)
    photos = {p.id: p.photo for p in out}
    assert photos["t"].url == "https://thumb.wikimedia.org/a.jpg" and "Wikipedia" in photos["t"].attribution
    # No matching photo: a labelled illustration of the kind, never the mismatched article's image.
    assert all(stand_in(photos[k]) for k in "cxr") and "b.jpg" not in photos["c"].url and "evil" not in photos["x"].url
    assert "Quán Bún" not in calls  # restaurants are not looked up on Wikipedia


@pytest.mark.asyncio
async def test_enrich_never_fails_the_search():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    places = [place("t", "Lăng Tự Đức")]
    out = await WikipediaImages(transport=transport).enrich(places)
    assert [p.name for p in out] == ["Lăng Tự Đức"] and stand_in(out[0].photo)


@pytest.mark.asyncio
async def test_google_photo_proxy_serves_only_issued_names_and_hides_the_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"photoUri": "https://lh3.googleusercontent.com/p/abc"})

    proxy = GooglePhotoProxy("secret-key", transport=httpx.MockTransport(handler))
    path = proxy.register("places/ChIJabc/photos/AXyz-1_2")
    assert path == "/api/v1/places/photo?ref=places/ChIJabc/photos/AXyz-1_2"
    assert proxy.register("https://evil.example/x") is None
    assert await proxy.resolve("places/other/photos/notissued") is None and not seen
    uri = await proxy.resolve("places/ChIJabc/photos/AXyz-1_2")
    assert uri == "https://lh3.googleusercontent.com/p/abc" and "secret-key" not in uri
    assert seen[0].headers["X-Goog-Api-Key"] == "secret-key"
    await proxy.resolve("places/ChIJabc/photos/AXyz-1_2")
    assert len(seen) == 1  # cached


def router(routes):
    """MockTransport answering by host + action, recording every request."""
    seen = []

    def handler(request):
        seen.append(request)
        key = (request.url.host, request.url.params.get("action"), request.url.params.get("list"))
        for (host, action, lst), body in routes.items():
            if key == (host, action, lst):
                return httpx.Response(200, json=body(request) if callable(body) else body)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler), seen


COMMONS_INFO = {"query": {"pages": [{"imageinfo": [{
    "thumburl": "https://upload.wikimedia.org/thumb/x.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
    "extmetadata": {"Artist": {"value": "<a href='u'>Nguyễn A</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}},
}]}]}}


def wikidata_routes(lat):
    return {
        ("www.wikidata.org", "wbsearchentities", None): {"search": [{"id": "Q1", "label": "Chùa Thiên Mụ"}]},
        ("www.wikidata.org", "wbgetentities", None): {"entities": {"Q1": {"claims": {
            "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": lat, "longitude": 107.0}}}}],
            "P18": [{"mainsnak": {"datavalue": {"value": "X.jpg"}}}],
        }}}},
        ("commons.wikimedia.org", "query", None): COMMONS_INFO,
    }


@pytest.mark.asyncio
async def test_wikidata_image_needs_matching_label_and_nearby_coordinates():
    near, _ = router(wikidata_routes(16.0))
    out = await WikipediaImages(transport=near).enrich([place("w", "Chùa Thiên Mụ", ["restaurant"])])
    assert out[0].photo.url == "https://upload.wikimedia.org/thumb/x.jpg"
    assert "Nguyễn A" in out[0].photo.attribution and "CC BY-SA 4.0" in out[0].photo.attribution
    far, _ = router(wikidata_routes(17.0))  # ~110 km away: a different place with the same name
    far_photo = (await WikipediaImages(transport=far).enrich([place("w", "Chùa Thiên Mụ", ["restaurant"])]))[0].photo
    assert stand_in(far_photo) and far_photo.url != "https://upload.wikimedia.org/thumb/x.jpg"


@pytest.mark.asyncio
async def test_commons_nearby_needs_a_distinctive_shared_word():
    def geo(titles):
        return {
            ("commons.wikimedia.org", "query", "geosearch"): {"query": {"geosearch": [{"title": t} for t in titles]}},
            ("commons.wikimedia.org", "query", None): COMMONS_INFO,
        }

    match, _ = router(geo(["File:Street in Hue.jpg", "File:Thong Dalat Space interior.jpg"]))
    out = await WikipediaImages(transport=match).enrich([place("c", "Thong Dalat Space", ["cafe"])])
    assert out[0].photo is not None
    generic, _ = router(geo(["File:Cafe in Hue city.jpg"]))  # only generic words shared
    generic_photo = (await WikipediaImages(transport=generic).enrich([place("c", "Hue Cafe", ["cafe"])]))[0].photo
    assert stand_in(generic_photo) and "cà phê" in generic_photo.attribution


@pytest.mark.parametrize("name,types,title", [
    ("Bún bò Huế Kim Đồng", ["restaurant"], "Bún bò Huế"),
    ("COM TAM DAN DA", ["restaurant"], "Cơm tấm"),            # no accents: still matched
    ("BBQ Nuong Khoi Hoi An", ["restaurant"], "Nướng"),
    ("Quán cô Sáu Mì Quảng", ["restaurant"], "Mì Quảng"),
    ("Phở Thìn", ["restaurant"], "Phở"),
    ("Pho Hoi Restaurant", ["restaurant"], "Ẩm thực Việt Nam"),  # "pho" without accents may be "phố"
    ("Lago Coffee House", ["cafe"], "Quán cà phê"),
    ("Ganesh Indian Restaurant", ["restaurant"], "Ẩm thực Ấn Độ"),
    ("Bảo tàng Hội An", ["museum"], None),                    # sights are never illustrated
    ("Lẩu đài", ["hotel"], None),
])
def test_food_places_are_illustrated_by_the_dish_in_their_name(name, types, title):
    found = dish_for(place("x", name, types))
    assert (found[0] if found else None) == title


@pytest.mark.asyncio
async def test_a_restaurant_without_a_photo_gets_a_labelled_dish_illustration_fetched_once():
    def article(request):
        title = request.url.params.get("titles")
        return {"query": {"pages": [{"title": title, "fullurl": "https://vi.wikipedia.org/wiki/x",
                                     "thumbnail": {"source": f"https://upload.wikimedia.org/{len(title)}.jpg"}}]}}

    transport, seen = router({("vi.wikipedia.org", "query", None): article})
    out = await WikipediaImages(transport=transport).enrich([
        place("a", "Bún bò Huế O Phượng", ["restaurant"]), place("b", "Bún bò Mệ Kéo", ["restaurant"]),
    ])
    for p in out:
        assert p.photo.illustration and "minh hoạ" in p.photo.attribution and "không phải ảnh của quán" in p.photo.attribution
    asked = [r for r in seen if r.url.params.get("titles") == "Bún bò Huế"]
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_english_names_of_sights_are_looked_up_on_english_wikipedia():
    transport, seen = router({})
    await WikipediaImages(transport=transport).enrich([
        place("e", "Hoi An Museum of Traditional Medicine", ["museum"]), place("v", "Bảo tàng Gốm sứ", ["museum"]),
    ])
    english = {r.url.params.get("gsrsearch") for r in seen if r.url.host == "en.wikipedia.org"}
    assert english == {"Hoi An Museum of Traditional Medicine"}  # Vietnamese names stay on vi.wikipedia
