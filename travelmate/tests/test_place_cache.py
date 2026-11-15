"""A complete place search is kept a day per destination; degraded ones are not."""

import asyncio

import pytest
from test_open_data_provider import FakeGeo, FakeWiki, HangingGeo, place, trip, wiki_place

from app.core.models import PlaceResult
from app.main import CachingProvider
from app.memory.store import Store
from app.tools.places.open_data_provider import OpenDataProvider


class Inner:
    def __init__(self, complete=True):
        self.complete, self.calls = complete, 0

    async def search_cacheable(self, trip):
        self.calls += 1
        return PlaceResult(places=[place(f"p{self.calls}", ["museum"], "Bảo tàng A")]), self.complete

    async def forecast(self, trip):
        return "weather"


@pytest.mark.asyncio
async def test_second_search_for_the_same_city_comes_from_the_database(tmp_path):
    inner, store = Inner(), Store(tmp_path / "c.sqlite3")
    cached = CachingProvider(inner, store, "open_data")
    first = await cached.search(trip())
    again = await CachingProvider(inner, Store(tmp_path / "c.sqlite3"), "open_data").search(
        trip().model_copy(update={"destination": "  da   NANG "}))  # a restarted server, other spelling
    assert inner.calls == 1 and again.places[0].id == first.places[0].id == "p1"
    assert await cached.forecast(trip()) == "weather"  # everything else passes through


@pytest.mark.asyncio
async def test_degraded_or_expired_results_are_searched_again(tmp_path):
    store = Store(tmp_path / "c.sqlite3")
    degraded = Inner(complete=False)
    for _ in range(2):
        await CachingProvider(degraded, store, "open_data").search(trip())
    assert degraded.calls == 2
    fresh = Inner()
    await CachingProvider(fresh, store, "open_data", ttl_s=0).search(trip())
    await asyncio.sleep(0.01)
    await CachingProvider(fresh, store, "open_data", ttl_s=0).search(trip())
    assert fresh.calls == 2


@pytest.mark.asyncio
async def test_a_broken_cache_never_breaks_planning(tmp_path):
    class Broken:
        def cached_places(self, key, max_age_s):
            raise OSError("database down")

        def cache_places(self, key, data):
            raise OSError("database down")

    inner = Inner()
    assert (await CachingProvider(inner, Broken(), "open_data").search(trip())).places


@pytest.mark.asyncio
async def test_open_data_says_when_a_result_is_complete():
    _, ok = await OpenDataProvider(images=False, geo=FakeGeo()).search_cacheable(trip())
    assert ok
    _, overpass_down = await OpenDataProvider(images=False, geo=FakeGeo(broken={"overpass"})).search_cacheable(trip())
    assert not overpass_down
    wiki = FakeWiki([wiki_place(1, "Lăng Tự Đức")])
    _, from_wiki = await OpenDataProvider(images=False, geo=HangingGeo(), wiki=wiki).search_cacheable(trip())
    assert not from_wiki
