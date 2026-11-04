"""Keyless live provider for the itinerary API.

Places come from Photon/OpenStreetMap around a GeoNames/Open-Meteo locality, weather
from the Open-Meteo forecast. No API key is needed; only the LLM planner needs one.
Coverage is community data, not an exhaustive or verified list, and the responses
say so.
"""

import asyncio
import time

from .agents import AgentError
from .geo_places import GeoPlaceService, LocalityChoiceRequired
from .models import Context, PlaceResult, WeatherDay, WeatherResult
from .place_media import WikipediaImages
from .ticket_prices import apply_tickets

SOURCE_NOTE = (
    "Địa điểm từ OpenStreetMap qua Photon (dữ liệu cộng đồng, ODbL); có thể thiếu hoặc cũ, "
    "chưa xác minh giờ mở cửa, giá hay tình trạng hoạt động."
)
LOCALITY_TTL_S = 600
# Lower ranks first. Within a rank the source's distance order is kept, so landmarks beat
# the nearest park or statue without leaving the search radius.
ATTRACTION_RANK = {
    "museum": 0, "castle": 0, "tomb": 0, "temple": 0, "archaeological_site": 1, "attraction": 1, "gallery": 1, "viewpoint": 1,
    "monument": 2, "zoo": 2, "theme_park": 2, "aquarium": 2, "beach": 2, "cave_entrance": 2,
    "peak": 2, "national_park": 2, "nature_reserve": 2, "memorial": 3, "park": 3,
}
MEAL_TYPES = {"restaurant", "food_court", "fast_food"}
# Photon gives no popularity signal (no wikidata, landmarks are plain nodes), so Vietnamese
# heritage words in the name stand in for "this is a sight", and generic centres rank later.
HERITAGE_WORDS = (
    "bảo tàng", "hoàng thành", "kinh thành", "tử cấm", "điện ", "lăng ", "chùa", "đền ", "đình ",
    "cung ", "thành cổ", "phố cổ", "nhà thờ", "tháp ", "hội quán", "di tích", "museum", "citadel",
    "pagoda", "temple", "tomb", "cathedral",
)
GENERIC_WORDS = ("trung tâm", "centre", "center", "nhà văn hóa")


def plausible_name(name):
    """Drop OSM records whose name is a note or a fragment, not a place name.

    Real names start with a capital letter or a digit ("3 Ngon"); notes such as
    "illegal entrance to palace, climb over" or fragments like "tan." do not.
    """
    name = name.strip()
    letters = sum(ch.isalpha() for ch in name)
    first = next((ch for ch in name if ch.isalnum()), "")
    return 4 <= letters and len(name) <= 70 and (first.isdigit() or first.isupper())


def unique_plausible(places):
    seen, out = set(), []
    for place in places:
        key = " ".join(place.name.casefold().split())
        if key in seen or not plausible_name(place.name):
            continue
        seen.add(key)
        out.append(place)
    return out


def attraction_rank(place):
    """Lower is a stronger sight: kind, heritage words in the name, generic centres last."""
    name = place.name.casefold() + " "
    base = min(ATTRACTION_RANK.get(t, 2) for t in place.types or ["?"])
    if any(word in name for word in HERITAGE_WORDS):
        base -= 2
    if any(word in name for word in GENERIC_WORDS):
        base += 3  # a museum-tagged "centre" ranks with parks, after monuments
    return base


def rank_candidates(places, category):
    """Drop junk/duplicate names; for sights, landmarks first (stable within a rank)."""
    places = unique_plausible(places)
    return sorted(places, key=attraction_rank) if category == "attraction" else places


def pick_attractions(places, limit, max_parks, max_per_kind=5):
    """Landmarks first, but no single kind (e.g. museums) fills the whole list."""
    rank = attraction_rank
    out, counts = [], {}
    for place in sorted(unique_plausible(places), key=rank):
        kind = place.types[0] if place.types else "?"
        cap = max_parks if kind == "park" else max_per_kind
        if counts.get(kind, 0) >= cap:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        out.append(place)
        if len(out) == limit:
            break
    return out


def pick_food(places, meals, cafes):
    places = unique_plausible(places)
    meal = [p for p in places if MEAL_TYPES & set(p.types)][:meals]
    cafe = [p for p in places if "cafe" in p.types and p not in meal][:cafes]
    return meal + cafe


class OpenDataProvider:
    """Implements search(trip), forecast(trip) and search_places(query) like the other providers."""

    def __init__(
        self, geo=None, weather=None, radius_m=5000, attractions=12, meals=5, cafes=2, max_parks=2,
        heritage_radius_m=15000, heritage=8, stays=5, images=None,
    ):
        self.geo = geo or GeoPlaceService()
        self.weather = weather  # a WeatherSpecialist; created lazily
        self.radius_m = radius_m
        self.heritage_radius_m, self.heritage = heritage_radius_m, heritage
        self.stay_limit = stays
        self.images = images if images is not None else WikipediaImages()
        self.pickers = {
            "attraction": lambda found: pick_attractions(found, attractions, max_parks),
            "restaurant": lambda found: pick_food(found, meals, cafes),
        }
        self._localities = {}
        self._lock = asyncio.Lock()

    async def locate(self, destination):
        """Resolve a destination to one locality, picking the top match when ambiguous."""
        key = destination.casefold().strip()
        async with self._lock:
            cached = self._localities.get(key)
            if cached and time.monotonic() - cached[0] < LOCALITY_TTL_S:
                return cached[1], list(cached[2])
            notes = []
            try:
                location = await self.geo.resolve(destination, None, "nearby")
            except LocalityChoiceRequired as exc:
                if not exc.choices:
                    raise AgentError(f"Không tìm thấy địa danh “{destination}” ở Việt Nam") from None
                location = exc.choices[0]
                where = ", ".join(part for part in [location.name, location.admin1] if part)
                notes.append(
                    f"“{destination}” khớp {len(exc.choices)} địa danh; đang dùng {where}. "
                    "Ghi rõ tỉnh/thành nếu đây không phải nơi bạn muốn."
                )
            self._localities[key] = (time.monotonic(), location, notes)
            return location, list(notes)

    async def search(self, trip):
        location, warnings = await self.locate(trip.destination)
        places, failures = [], 0
        for category, pick in self.pickers.items():
            try:
                found, _, _ = await self.geo.discover(location, category, self.radius_m)
            except AgentError:
                failures += 1
                continue
            places.extend(pick(found))
        places.extend(await self.heritage_sites(location, places))
        places = await self.images.enrich(places) if self.images else places
        places = apply_tickets(places, trip.destination)
        stays = await self.stays(location)
        if failures == len(self.pickers):
            raise AgentError("Nguồn địa điểm không phản hồi")
        if failures:
            warnings.append("Một nhóm địa điểm không tải được; danh sách có thể thiếu.")
        if not places:
            warnings.append(f"Không thấy địa điểm trong bán kính {self.radius_m // 1000} km quanh trung tâm.")
        return PlaceResult(places=places, warnings=warnings + [SOURCE_NOTE], stays=stays)

    async def stays(self, location):
        """Nearby accommodation from OSM: names and locations only, no nightly prices."""
        if not self.stay_limit:
            return []
        try:
            found, _, _ = await self.geo.discover(location, "hotel", self.radius_m)
        except AgentError:
            return []
        return unique_plausible(found)[: self.stay_limit]

    async def heritage_sites(self, location, already):
        """Royal tombs and historic temples often lie outside the city-centre radius."""
        if not self.heritage:
            return []
        try:
            found, _, _ = await self.geo.discover(location, "heritage", self.heritage_radius_m)
        except AgentError:
            return []  # optional extra; the main lists already succeeded or failed on their own
        taken = {" ".join(p.name.casefold().split()) for p in already}
        fresh = [p for p in unique_plausible(found) if " ".join(p.name.casefold().split()) not in taken]
        # Named sites ("Lăng Tự Đức") before unnamed-looking ones; distance order within each.
        fresh.sort(key=lambda p: not any(w in p.name.casefold() + " " for w in HERITAGE_WORDS))
        return fresh[: self.heritage]

    async def search_places(self, query):
        location, warnings = await self.locate(query.destination)
        found, _, _ = await self.geo.discover(location, query.category, query.radius_m, query.keyword)
        return PlaceResult(places=unique_plausible(found)[: query.limit], warnings=warnings + [SOURCE_NOTE])

    async def forecast(self, trip):
        from .specialists.weather import WeatherRequest, WeatherSpecialist

        location, _ = await self.locate(trip.destination)
        weather = self.weather or WeatherSpecialist()
        report = await weather.run(
            WeatherRequest(
                latitude=location.latitude,
                longitude=location.longitude,
                start_date=trip.start_date,
                end_date=trip.end_date,
            ),
            Context(),
        )
        days = [WeatherDay(date=d.date, weather_code=d.weather_code) for d in report.days if d.weather_code is not None]
        warnings = list(report.warnings)
        for d in report.days:
            if d.outdoor_risk == "elevated":
                chance = f" ({d.precipitation_probability}% khả năng mưa)" if d.precipitation_probability is not None else ""
                warnings.append(f"{d.date.isoformat()}: thời tiết có thể không thuận cho hoạt động ngoài trời{chance}.")
        if report.missing_dates:
            warnings.append(
                "Chưa có dự báo cho: " + ", ".join(day.isoformat() for day in report.missing_dates) + "."
            )
        return WeatherResult(days=days, warnings=warnings + ["Thời tiết: dự báo Open-Meteo."])
