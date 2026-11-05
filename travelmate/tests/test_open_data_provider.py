"""Keyless live provider: picks a locality, merges POI categories, maps the forecast."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_planning import payload

from app.agents import AgentError
from app.geo_places import Locality, LocalityChoiceRequired
from app.main import Settings, create_app
from app.models import Place, PlaceSearchRequest, TripRequest
from app.open_data_provider import OpenDataProvider, pick_attractions, pick_food, plausible_name
from app.specialists.weather import ForecastDay, WeatherReport


def locality(name="Hội An", admin1="Đà Nẵng", ident="geonames:1"):
    return Locality(
        id=ident, name=name, admin1=admin1, latitude=15.88, longitude=108.33, feature_code="PPL",
        source_url="https://example.test", fetched_at=datetime.now(UTC),
    )


def place(ident, types, name=None):
    return Place(
        id=ident, name=name or ident.title(), address="addr", latitude=15.88, longitude=108.33,
        source="osm", types=types,
    )


class FakeGeo:
    def __init__(self, ambiguous=False, empty=False, broken=()):
        self.ambiguous, self.empty, self.broken = ambiguous, empty, set(broken)
        self.resolves = 0
        self.discovered = []

    async def resolve(self, destination, selected_id, scope):
        self.resolves += 1
        assert scope == "nearby"
        if self.empty:
            raise LocalityChoiceRequired([], "none")
        if self.ambiguous:
            raise LocalityChoiceRequired([locality(), locality(admin1="Quảng Ngãi", ident="geonames:2")], "many")
        return locality()

    async def discover(self, location, category, radius_m, keyword=""):
        self.discovered.append((category, radius_m, keyword))
        if category in self.broken:
            raise AgentError("source down")
        return [place(f"{category}-{i}", [category]) for i in range(10)], {}, 0


class FakeWeather:
    def __init__(self):
        self.requests = []

    async def run(self, data, context):
        self.requests.append(data)
        return WeatherReport(
            status="partial", latitude=data.latitude, longitude=data.longitude, timezone=data.timezone,
            fetched_at=datetime.now(UTC),
            days=[
                ForecastDay(date=data.start_date, weather_code=63, precipitation_probability=80, outdoor_risk="elevated"),
            ],
            missing_dates=[data.end_date], warnings=["Nguồn Open-Meteo."],
        )


def trip():
    return TripRequest(**payload())


@pytest.mark.asyncio
async def test_search_merges_capped_categories_with_source_note():
    geo = FakeGeo()
    result = await OpenDataProvider(images=False, geo=geo, attractions=3, meals=2, cafes=0, heritage=0).search(trip())
    assert [p.id for p in result.places] == [
        "attraction-0", "attraction-1", "attraction-2", "restaurant-0", "restaurant-1",
    ]
    assert any("OpenStreetMap" in w for w in result.warnings)


@pytest.mark.parametrize(
    "name,ok",
    [
        ("Hoàng Thành Huế", True), ("3 Ngon", True), ("Nina's Cafe", True),
        ("illegal entrance to palace, climb over", False), ("tan.", False), ("Chè", False),
        ("Street Food - " + "bánh xèo, " * 10, False),
    ],
)
def test_plausible_name_drops_osm_notes_and_fragments(name, ok):
    assert plausible_name(name) is ok


def test_attractions_prefer_heritage_cap_kinds_and_dedupe():
    nearest_first = [
        place("p1", ["park"], "Công viên A"), place("p2", ["park"], "Công viên B"),
        place("p3", ["park"], "Công viên C"), place("c1", ["museum"], "Trung tâm Thanh thiếu nhi"),
        place("m1", ["museum"], "Bảo tàng Cổ vật"), place("m1b", ["museum"], "bảo tàng cổ vật"),
        place("h1", ["attraction"], "Hoàng Thành Huế"), place("x1", ["attraction"], "illegal entrance, climb over"),
        place("s1", ["monument"], "Tượng đài X"),
    ]
    picked = [p.id for p in pick_attractions(nearest_first, limit=6, max_parks=2)]
    assert picked[:2] == ["m1", "h1"]  # heritage names first, nearest order kept within a rank
    assert "x1" not in picked and "m1b" not in picked  # junk and duplicate dropped
    assert sum(p.startswith("p") for p in picked) == 2  # park cap
    assert picked.index("c1") > picked.index("s1")  # generic centres rank after monuments
    many_museums = [place(f"m{i}", ["museum"], f"Bảo tàng {i}") for i in range(8)]
    assert len(pick_attractions(many_museums, limit=8, max_parks=2)) == 5  # per-kind cap


def test_food_splits_meals_and_cafes():
    found = [place(f"c{i}", ["cafe"], f"Cafe {i}") for i in range(4)] + [
        place("r1", ["restaurant"], "Quán Bún"), place("f1", ["fast_food"], "Bánh Mì"),
    ]
    assert [p.id for p in pick_food(found, meals=5, cafes=2)] == ["r1", "f1", "c0", "c1"]


@pytest.mark.asyncio
async def test_ambiguous_destination_uses_top_match_and_says_so():
    result = await OpenDataProvider(images=False, geo=FakeGeo(ambiguous=True)).search(trip())
    assert result.places
    assert any("khớp 2 địa danh" in w and "Đà Nẵng" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_unknown_destination_is_an_error():
    with pytest.raises(AgentError, match="Không tìm thấy địa danh"):
        await OpenDataProvider(images=False, geo=FakeGeo(empty=True)).search(trip())


@pytest.mark.asyncio
async def test_one_failed_category_is_partial_all_failed_is_error():
    partial = await OpenDataProvider(images=False, geo=FakeGeo(broken={"restaurant"})).search(trip())
    assert partial.places and any("không tải được" in w for w in partial.warnings)
    with pytest.raises(AgentError, match="không phản hồi"):
        await OpenDataProvider(images=False, geo=FakeGeo(broken={"restaurant", "attraction"})).search(trip())


@pytest.mark.asyncio
async def test_locality_is_resolved_once_for_search_and_forecast():
    import asyncio

    geo = FakeGeo()
    provider = OpenDataProvider(images=False, geo=geo, weather=FakeWeather())
    await asyncio.gather(provider.search(trip()), provider.forecast(trip()))
    assert geo.resolves == 1


@pytest.mark.asyncio
async def test_forecast_maps_days_rain_risk_and_missing_dates():
    weather = FakeWeather()
    t = trip()
    result = await OpenDataProvider(images=False, geo=FakeGeo(), weather=weather).forecast(t)
    assert weather.requests[0].latitude == 15.88
    assert [d.weather_code for d in result.days] == [63]
    text = " ".join(result.warnings)
    assert "80% khả năng mưa" in text and t.end_date.isoformat() in text


@pytest.mark.asyncio
class NamedGeo(FakeGeo):
    def __init__(self, names):
        super().__init__()
        self.names = names

    async def discover(self, location, category, radius_m, keyword=""):
        self.discovered.append((category, radius_m, keyword))
        hits = self.names.get(keyword, [])
        return [place(f"{category}-{keyword}-{i}", [category], name=n) for i, n in enumerate(hits)], {}, 0


async def test_search_places_passes_keyword_radius_and_limit():
    geo = NamedGeo({"chay": [f"Quán chay {i}" for i in range(6)]})
    result = await OpenDataProvider(images=False, geo=geo).search_places(
        PlaceSearchRequest(destination="Hội An", category="restaurant", keyword="chay", limit=4, radius_m=2000)
    )
    assert len(result.places) == 4
    assert geo.discovered[0] == ("restaurant", 2000, "chay")
    assert ("restaurant", 2000, "vegetarian") in geo.discovered  # English OSM names
    assert ("restaurant", 2000, "") in geo.discovered  # nearby list matched locally


async def test_keyword_search_respects_vietnamese_accents():
    geo = NamedGeo({"lăng": ["Làng tránh Sình", "Lăng Tự Đức"], "tomb": ["Tomb of Minh Mang"],
                    "": ["Khiêm Lăng", "Chợ Đông Ba"]})
    result = await OpenDataProvider(images=False, geo=geo).search_places(
        PlaceSearchRequest(destination="Huế", category="attraction", keyword="lăng", limit=10, radius_m=10000))
    names = [p.name for p in result.places]
    assert "Làng tránh Sình" not in names and "Chợ Đông Ba" not in names
    assert {"Lăng Tự Đức", "Khiêm Lăng", "Tomb of Minh Mang"} <= set(names)


def test_keyword_filter_drops_accent_lookalikes():
    from app.open_data_provider import keyword_filter, loosely_named

    named = [place(str(i), ["restaurant"], name=n) for i, n in enumerate(["Quần cháy", "Quan chay", "Liên Hoa"])]
    assert [p.name for p in keyword_filter(named, "chay")] == ["Quan chay", "Liên Hoa"]
    assert [p.name for p in keyword_filter(named[:1], "chay")] == ["Quần cháy"]  # nothing exact: keep fuzzy
    assert not loosely_named(place("x", ["restaurant"], name="Phong Nha"), "phở")


def test_live_open_data_needs_no_maps_key_and_reports_provider():
    settings = Settings(
        _env_file=None, travelmate_mode="live", travelmate_place_provider="open_data",
        google_api_key="test-key", google_maps_api_key="", travelmate_api_token="t",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()
    assert health["mode"] == "live" and health["place_provider"] == "open_data"


def test_live_google_still_requires_maps_key():
    with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY"):
        create_app(Settings(
            _env_file=None, travelmate_mode="live", travelmate_place_provider="google",
            google_api_key="test-key", google_maps_api_key="", travelmate_api_token="t",
        ))


def test_open_data_plan_end_to_end_with_fakes():
    from app.agents import (
        BudgetAgent,
        MemoryAgent,
        PlaceAgent,
        PlannerAgent,
        RecommendationAgent,
        Registry,
        WeatherAgent,
    )
    from app.orchestrator import Orchestrator

    provider = OpenDataProvider(images=False, geo=FakeGeo(), weather=FakeWeather())
    registry = Registry()
    for agent in [MemoryAgent(), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                  PlannerAgent(), BudgetAgent()]:
        registry.register(agent)
    import asyncio

    result = asyncio.run(Orchestrator(registry, "live").plan(trip()))
    assert result.mode == "live" and result.draft.days
    assert result.weather.days[0].weather_code == 63
    assert date.fromisoformat(str(result.draft.days[0].date)) >= date.today() - timedelta(days=1)


class HeritageGeo(FakeGeo):
    def __init__(self, heritage_broken=False):
        super().__init__()
        self.heritage_broken = heritage_broken

    async def discover(self, location, category, radius_m, keyword=""):
        self.discovered.append((category, radius_m, keyword))
        if category == "heritage":
            if self.heritage_broken:
                raise AgentError("down")
            return [
                place("t0", ["tomb"], "Nguyên Phức Tộc"), place("t1", ["tomb"], "Lăng Tự Đức"),
                place("dup", ["museum"], "Attraction-0"), place("t2", ["tomb"], "Lăng Khải Định"),
            ], {}, 0
        return await super().discover(location, category, radius_m, keyword)


@pytest.mark.asyncio
async def test_heritage_sites_come_from_a_wider_radius_named_first_and_deduped():
    geo = HeritageGeo()
    result = await OpenDataProvider(images=False, geo=geo, heritage=2, heritage_radius_m=15000).search(trip())
    assert ("heritage", 15000, "") in geo.discovered
    ids = [p.id for p in result.places]
    assert ids[-2:] == ["t1", "t2"]  # "Lăng ..." before the unnamed-looking site
    assert "dup" not in ids  # same name as an attraction already picked


@pytest.mark.asyncio
async def test_heritage_failure_does_not_fail_the_search():
    result = await OpenDataProvider(images=False, geo=HeritageGeo(heritage_broken=True)).search(trip())
    assert result.places and not any(p.types == ["tomb"] for p in result.places)


@pytest.mark.asyncio
async def test_osm_stays_are_returned_apart_from_activities():
    result = await OpenDataProvider(images=False, geo=FakeGeo(), stays=3).search(trip())
    assert [p.id for p in result.stays] == ["hotel-0", "hotel-1", "hotel-2"]
    assert not any(p.id.startswith("hotel") for p in result.places)
