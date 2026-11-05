"""Wikipedia photos only when the article clearly is the place; Google photos only via allowlist."""

import httpx
import pytest

from app.models import Place
from app.place_media import GooglePhotoProxy, WikipediaImages, titles_match


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
    assert photos["c"] is None and photos["x"] is None and photos["r"] is None
    assert "Quán Bún" not in calls  # restaurants are not looked up on Wikipedia


@pytest.mark.asyncio
async def test_enrich_never_fails_the_search():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    places = [place("t", "Lăng Tự Đức")]
    assert await WikipediaImages(transport=transport).enrich(places) == places


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
    assert (await WikipediaImages(transport=far).enrich([place("w", "Chùa Thiên Mụ", ["restaurant"])]))[0].photo is None


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
    assert (await WikipediaImages(transport=generic).enrich([place("c", "Hue Cafe", ["cafe"])]))[0].photo is None
