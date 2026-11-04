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
