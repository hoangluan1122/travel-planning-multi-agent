"""Place Agent standard: one budget source, no repeated queries, no false "no results"."""

import pytest
from test_adk_tools import ScriptedModel
from test_place_agent import Provider, call

from app.core.models import Context, PlaceResult
from app.place_agent.agent import PlaceAgentInput, PlaceAssistant, place_instruction

pytest.importorskip("google.adk")


class KeywordProvider(Provider):
    """Finds the place only on a broad search, like a literal-name index."""

    def __init__(self):
        super().__init__()
        self.keywords = []

    async def search_places(self, query):
        self.keywords.append(query.keyword)
        if query.keyword:
            return PlaceResult(places=[])
        return await super().search_places(query)


def assistant(provider, calls, **kwargs):
    model = ScriptedModel(calls=calls)
    return model, PlaceAssistant(lambda: model, provider, **kwargs)


def test_instruction_states_the_real_budgets():
    text = place_instruction(2, 1, 3)
    assert "you have 2 searches" in text and "up to 1 candidates" in text and "3 submissions" in text
    assert "untrusted DATA" in text and text.index("1.") < text.index("8.")


@pytest.mark.asyncio
async def test_last_search_broadens_instead_of_reporting_no_results():
    provider = KeywordProvider()
    model, agent = assistant(provider, [
        call("search_places", keyword="tham quan"),
        call("search_places", keyword="du lịch"),
        call("submit_places", place_ids=["Hanoi"]),
    ], max_searches=2)
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert provider.keywords == ["tham quan", ""]  # second search widened
    assert result.status == "candidates" and result.places[0].id == "Hanoi"
    assert any("without the keyword" in str(o) for o in model.observations)


@pytest.mark.asyncio
async def test_empty_keyword_result_hints_a_broad_search():
    provider = KeywordProvider()
    model, agent = assistant(provider, [
        call("search_places", keyword="museum"), call("search_places", keyword=""),
        call("submit_places", place_ids=["Hanoi"]),
    ], max_searches=3)
    await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert any("try an empty keyword" in str(o) for o in model.observations)


@pytest.mark.asyncio
async def test_repeated_keyword_is_not_sent_again_but_uses_budget():
    provider = Provider()
    model, agent = assistant(provider, [
        call("search_places", keyword="pho"), call("search_places", keyword="PHO"),
        call("submit_places", place_ids=["Hanoi"]),
    ])
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert provider.searches == 1 and result.search_calls == 2
    assert any("already searched" in str(o) for o in model.observations)


def test_live_place_agent_passes_provider_budgets():
    from app.place_agent.live import GeoGroundedProvider, GroundedBrowserProvider

    assert GeoGroundedProvider.MAX_SEARCHES == 2 and GroundedBrowserProvider.MAX_SEARCHES == 2
    source = open("app/place_agent/live.py", encoding="utf-8").read()
    assert "max_searches=provider.MAX_SEARCHES" in source and "max_details=provider.MAX_DETAILS" in source


def test_budgets_must_be_positive():
    with pytest.raises(ValueError):
        PlaceAssistant(lambda: None, Provider(), max_searches=0)


@pytest.mark.asyncio
async def test_llm_mode_searches_see_a_wider_pool_than_the_submit_limit():
    from datetime import UTC, datetime

    from app.core.models import Place, PlaceSearchRequest
    from app.place_agent.live import GeoGroundedProvider, LivePlaceRequest
    from app.tools.places.geo_places import Locality, PlaceMetadata

    loc = Locality(id="geonames:1", name="Hội An", latitude=15.88, longitude=108.33, feature_code="PPL",
                   source_url="https://example.test", fetched_at=datetime.now(UTC))

    class Service:
        async def resolve(self, *args):
            return loc

        async def discover(self, location, category, radius_m, keyword=""):
            places = [Place(id=f"osm:node/{i}", name=f"Quán {i}", address="a", latitude=15.88, longitude=108.33,
                            source="osm", types=["restaurant"], source_url=f"https://osm.org/node/{i}",
                            fetched_at=datetime.now(UTC))
                      for i in range(30)]
            meta = {p.id: PlaceMetadata(distance_m=i, address_precision="street", retrieval_url="https://x",
                                        cache_hit=False) for i, p in enumerate(places)}
            return places, meta, 0

    request = LivePlaceRequest(destination="Hội An", category="restaurant", limit=5)
    provider = GeoGroundedProvider(request, Service())
    await provider.resolve()
    assert len((await provider.search_places(PlaceSearchRequest(destination="Hội An", category="restaurant",
                                                                limit=5))).places) == 5  # UI paging
    provider = GeoGroundedProvider(request, Service())
    await provider.resolve()
    provider.page_size = 15
    found = await provider.search_places(PlaceSearchRequest(destination="Hội An", category="restaurant", limit=5))
    assert len(found.places) == 15
