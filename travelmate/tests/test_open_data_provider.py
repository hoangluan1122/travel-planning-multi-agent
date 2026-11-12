"""Keyless live provider: picks a locality, merges POI categories, maps the forecast."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from test_planning import payload

from app.core.base import AgentError
from app.core.models import Place, PlaceSearchRequest, TripRequest
from app.main import Settings, create_app
from app.specialists.weather import ForecastDay, WeatherReport
from app.tools.places.geo_places import (
    GeoPlaceService,
    Locality,
    LocalityChoiceRequired,
    PublicGeoClient,
    name_pattern,
)
from app.tools.places.open_data_provider import OpenDataProvider, pick_attractions, pick_food, plausible_name


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
        if category == "landmark":
            return [], {}, 0
        return [place(f"{category}-{i}", [category]) for i in range(10)], {}, 0

    async def landmarks(self, location, radius_m, keyword=""):
        self.discovered.append(("overpass", radius_m, keyword))
        if "overpass" in self.broken:
            raise AgentError("overpass at capacity")
        return []

    async def province_seat(self, destination):
        return None


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
        await OpenDataProvider(images=False, wiki=False, geo=FakeGeo(broken={"restaurant", "attraction"})).search(trip())


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
    from app.tools.places.open_data_provider import keyword_filter, loosely_named

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
    from app.agents.budget import BudgetAgent
    from app.agents.itinerary import PlannerAgent
    from app.agents.orchestrator import Orchestrator
    from app.agents.place import PlaceAgent
    from app.agents.recommendation import RecommendationAgent
    from app.agents.weather import WeatherAgent
    from app.core.base import Registry
    from app.memory.preferences import MemoryAgent

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


# --- Landmark search (2026-11-05 live failures: Văn Miếu, Ngũ Hành Sơn, Tràng An, Ninh Bình) ---

HANOI = dict(name="Hà Nội", admin1="Hanoi", ident="geonames:1581130")


def at(lat, lon, **extra):
    return locality(**extra).model_copy(update={"latitude": lat, "longitude": lon})


def photon(ident, name, key, value, lon, lat, osm_type="R"):
    return {
        "type": "Feature",
        "properties": {"name": name, "osm_type": osm_type, "osm_id": ident, "osm_key": key,
                       "osm_value": value, "countrycode": "VN"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


class HttpGeo(GeoPlaceService):
    """The real Photon/Overpass parsing over fake HTTP; only the locality is fixed."""

    def __init__(self, where, landmark_features=(), overpass=None, overpass_status=200):
        self.calls = []

        def handler(request):
            self.calls.append(request)
            if request.url.host == "overpass.test":
                if overpass_status != 200:
                    return httpx.Response(overpass_status, text="at capacity")
                return httpx.Response(200, json={"elements": overpass or []})
            tags = request.url.params.get_list("osm_tag")
            features = list(landmark_features) if "landuse:religious" in tags else []
            return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

        super().__init__(
            client=PublicGeoClient(transport=httpx.MockTransport(handler), interval=0),
            photon_url="https://photon.test", overpass_url="https://overpass.test/api/interpreter",
        )
        self.where = where

    async def resolve(self, destination, selected_id, scope):
        return self.where


def search(destination, keyword, **extra):
    return PlaceSearchRequest(destination=destination, category="attraction", keyword=keyword, **extra)


@pytest.mark.asyncio
async def test_landmark_tagged_natural_wood_outside_default_radius_is_found():
    # Ngũ Hành Sơn is natural=wood in Photon's index and ~8.5 km from the Đà Nẵng centre.
    geo = HttpGeo(at(16.06778, 108.22083, name="Đà Nẵng"), overpass_status=502, landmark_features=[
        photon(8552348, "Ngũ Hành Sơn", "natural", "wood", 108.2627745, 16.00402),
        photon(9, "Đường Ngũ Hành Sơn", "highway", "trunk", 108.2386, 16.0469, "W"),
    ])
    provider = OpenDataProvider(images=False, geo=geo)
    result = await provider.search_places(search("Đà Nẵng", "ngũ hành sơn"))
    assert [(p.name, p.types) for p in result.places] == [("Ngũ Hành Sơn", ["attraction"])]
    landmark = next(r for r in geo.calls if "landuse:religious" in r.url.params.get_list("osm_tag"))
    x0, _, x1, _ = map(float, landmark.url.params["bbox"].split(","))
    assert x1 - x0 > 0.25  # a 15 km box, not the request's 3 km radius
    # Overpass at capacity: the search still works and the next one does not wait on it.
    await provider.search_places(search("Đà Nẵng", "ngũ hành sơn", limit=5))
    assert sum(r.url.host == "overpass.test" for r in geo.calls) == 1


@pytest.mark.asyncio
async def test_heritage_landmark_from_overpass_ranks_before_its_gate_building():
    # Văn Miếu – Quốc Tử Giám: landuse=religious + heritage=2, invisible to a tourism-tag search.
    overpass = [
        {"type": "relation", "id": 21422528, "center": {"lat": 21.0287903, "lon": 105.8359533},
         "tags": {"name": "Văn Miếu - Quốc Tử Giám", "landuse": "religious", "heritage": "2"}},
        {"type": "way", "id": 691421444, "center": {"lat": 21.026, "lon": 105.835},
         "tags": {"name": "Trường Tiểu học Văn Miếu", "amenity": "school", "historic": "yes"}},
        {"type": "relation", "id": 12413584, "center": {"lat": 21.025, "lon": 105.834},
         "tags": {"name": "Phường Văn Miếu", "boundary": "historic", "heritage": "3"}},
    ]
    geo = HttpGeo(at(21.0245, 105.84117, **HANOI), overpass=overpass, landmark_features=[
        photon(1, "Văn Miếu Môn", "building", "yes", 105.8355176, 21.0276496, "W"),
        photon(21422528, "Văn Miếu - Quốc Tử Giám", "landuse", "religious", 105.8359533, 21.0287903),
    ])
    result = await OpenDataProvider(images=False, geo=geo).search_places(search("Hà Nội", "văn miếu"))
    assert [p.name for p in result.places] == ["Văn Miếu - Quốc Tử Giám", "Văn Miếu Môn"]
    assert result.places[0].types == ["temple"] and result.places[0].source == "osm_overpass"
    query = next(r for r in geo.calls if r.url.host == "overpass.test").url.params["data"]
    assert '"name"~"(V|v)ăn +(M|m)iếu"' in query and "around:15000" in query


@pytest.mark.asyncio
async def test_tourist_area_building_is_kept_but_namesake_buildings_and_lookalikes_are_not():
    # Tràng An's boat-tour area is building=yes in Photon; flats and accent lookalikes are noise.
    geo = HttpGeo(at(20.2572, 105.9719, name="Hoa Lư"), overpass_status=504, landmark_features=[
        photon(474685617, "Khu Du lịch sinh Thái Tràng An", "building", "yes", 105.918, 20.2527, "W"),
        photon(2, "Chung cư Tràng An", "building", "yes", 105.96, 20.25, "W"),
        photon(3, "Trang An Đình", "amenity", "place_of_worship", 105.95, 20.25, "W"),
        photon(4, "Công viên văn hóa Tràng An", "leisure", "park", 105.9561, 20.2625, "W"),
    ])
    result = await OpenDataProvider(images=False, geo=geo).search_places(search("Ninh Bình", "tràng an"))
    assert [p.name for p in result.places] == ["Khu Du lịch sinh Thái Tràng An", "Công viên văn hóa Tràng An"]


def test_overpass_name_pattern_keeps_accents_exact_or_expands_plain_keywords():
    assert name_pattern("lăng") == "(L|l)ăng"
    assert name_pattern("Ngũ  Hành") == "(N|n)gũ +(H|h)ành"
    plain_pattern = name_pattern("van mieu")
    assert "ă" in plain_pattern and "ế" in plain_pattern and plain_pattern.startswith("(V|v)(")
    assert name_pattern("den").startswith("(D|d|Đ|đ)") and name_pattern("dền") == "(D|d)ền"


class ProvinceGeo(FakeGeo):
    def __init__(self, choices, seat):
        super().__init__()
        self.choices, self.seat, self.seat_calls = choices, seat, 0

    async def resolve(self, destination, selected_id, scope):
        raise LocalityChoiceRequired(self.choices, "many")

    async def province_seat(self, destination):
        self.seat_calls += 1
        return self.seat


@pytest.mark.asyncio
async def test_province_name_uses_its_city_not_a_namesake_village_elsewhere():
    villages = [at(15.7, 108.01667, name="Ninh Bình", admin1="Đà Nẵng", ident="geonames:1571966"),
                at(12.48333, 109.06667, name="Ninh Bình", admin1="Khanh Hoa", ident="geonames:1571969")]
    hoa_lu = at(20.2572484, 105.9718894, name="Hoa Lư", admin1="Tỉnh Ninh Bình", ident="photon:relation/19539208")
    geo = ProvinceGeo(villages, hoa_lu)
    location, notes = await OpenDataProvider(images=False, geo=geo).locate("Ninh Bình")
    assert location.name == "Hoa Lư" and "là tên tỉnh" in notes[0]
    # A province whose capital matched already (Hà Nội PPLC) needs no extra lookup.
    capital = at(21.0245, 105.84117, **HANOI).model_copy(update={"feature_code": "PPLC"})
    namesake = at(20.47366, 106.02292, name="Hà Nội", admin1="Ninh Binh", ident="geonames:8564175")
    geo = ProvinceGeo([namesake, capital], hoa_lu)
    location, _ = await OpenDataProvider(images=False, geo=geo).locate("Hà Nội")
    assert location.id == "geonames:1581130" and geo.seat_calls == 0


@pytest.mark.asyncio
async def test_province_seat_is_a_city_inside_the_province_polygon():
    features = [
        photon(1903516, "Hà Nội", "place", "city", 105.854041, 21.0283334),  # outside the province
        photon(5, "Phát Diệm", "place", "town", 106.08, 20.09, "N"),
        photon(19539208, "Hoa Lư", "place", "city", 105.9718894, 20.2572484),
    ]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    geo = GeoPlaceService(client=PublicGeoClient(transport=httpx.MockTransport(handler), interval=0),
                          photon_url="https://photon.test")
    seat = await geo.province_seat("Ninh Bình")
    assert seat.name == "Hoa Lư" and seat.id == "photon:relation/19539208"
    assert requests[0].url.params["include"] == "osm.place.city,osm.place.town"
    assert await geo.province_seat("Hội An") is None  # not a province name: no lookup
    assert len(requests) == 1


class LandmarkGeo(HeritageGeo):
    async def landmarks(self, location, radius_m, keyword=""):
        self.discovered.append(("overpass", radius_m, keyword))
        return [place("vm", ["temple"], "Văn Miếu - Quốc Tử Giám"), place("dup2", ["museum"], "Attraction-1")]


@pytest.mark.asyncio
async def test_default_search_adds_heritage_landmarks_before_photon_heritage():
    geo = LandmarkGeo()
    result = await OpenDataProvider(images=False, geo=geo, heritage=4).search(trip())
    ids = [p.id for p in result.places]
    assert ("overpass", 15000, "") in geo.discovered
    assert ids.index("vm") < ids.index("t1") and "dup2" not in ids
    broken = await OpenDataProvider(images=False, geo=FakeGeo(broken={"overpass"})).search(trip())
    assert broken.places  # Overpass down: Photon lists still returned


class FakeWiki:
    def __init__(self, places=()):
        self.places, self.calls = list(places), 0

    async def nearby(self, location, radius_m):
        self.calls += 1
        return self.places


def wiki_place(pageid, name):
    return place(f"wikipedia:vi/{pageid}", ["tomb"], name).model_copy(update={"source": "wikipedia"})


class HangingGeo(FakeGeo):
    async def discover(self, location, category, radius_m, keyword=""):
        self.discovered.append((category, radius_m, keyword))
        raise TimeoutError("Geographic source timed out")


@pytest.mark.asyncio
async def test_photon_timeout_falls_back_to_wikipedia_sights_and_says_so():
    wiki = FakeWiki([wiki_place(1, "Lăng Tự Đức"), wiki_place(2, "Chùa Thiên Mụ")])
    result = await OpenDataProvider(images=False, geo=HangingGeo(), wiki=wiki).search(trip())
    assert {p.name for p in result.places} == {"Lăng Tự Đức", "Chùa Thiên Mụ"}
    assert result.stays == []
    assert any("Wikipedia" in w for w in result.warnings)
    assert not any(w.startswith("Địa điểm từ OpenStreetMap") for w in result.warnings)


@pytest.mark.asyncio
async def test_wikipedia_is_only_asked_when_photon_fails_and_an_empty_answer_still_fails():
    wiki = FakeWiki([place("wikipedia:vi/1", ["tomb"], "Lăng Tự Đức")])
    await OpenDataProvider(images=False, geo=FakeGeo(), wiki=wiki).search(trip())
    assert wiki.calls == 0
    with pytest.raises(AgentError, match="không phản hồi"):
        await OpenDataProvider(images=False, geo=HangingGeo(), wiki=FakeWiki()).search(trip())
