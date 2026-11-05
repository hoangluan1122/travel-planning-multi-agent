"""Keyless live provider for the itinerary API.

Places come from Photon/OpenStreetMap around a GeoNames/Open-Meteo locality, weather
from the Open-Meteo forecast. No API key is needed; only the LLM planner needs one.
Coverage is community data, not an exhaustive or verified list, and the responses
say so.
"""

import asyncio
import re
import time
import unicodedata

from .agents import AgentError
from .geo_places import GeoPlaceService, LocalityChoiceRequired
from .models import Context, PlaceResult, WeatherDay, WeatherResult
from .place_media import WikipediaImages, plain
from .ticket_prices import apply_tickets
from .vietnam_regions import load_catalog

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
    "pagoda", "temple", "tomb", "cathedral", "văn miếu", "quốc tử giám",
)
GENERIC_WORDS = ("trung tâm", "centre", "center", "nhà văn hóa")
# GeoNames/OSM locality kinds, most city-like first; anything else is a village or a sight.
CITY_CODES = ("PPLC", "PPLA", "OSM:city", "PPLA2", "OSM:town")


def city_rank(locality):
    code = locality.feature_code
    return CITY_CODES.index(code) if code in CITY_CODES else len(CITY_CODES)


def plausible_name(name):
    """Drop OSM records whose name is a note or a fragment, not a place name.

    Real names start with a capital letter or a digit ("3 Ngon"); notes such as
    "illegal entrance to palace, climb over" or fragments like "tan." do not.
    """
    name = name.strip()
    letters = sum(ch.isalpha() for ch in name)
    first = next((ch for ch in name if ch.isalnum()), "")
    return 4 <= letters and len(name) <= 70 and (first.isdigit() or first.isupper())


def name_key(place):
    return " ".join(place.name.casefold().split())


def unique_plausible(places):
    seen, out = set(), []
    for place in places:
        key = name_key(place)
        if key in seen or not plausible_name(place.name):
            continue
        seen.add(key)
        out.append(place)
    return out


SIGHT_AREA_WORDS = ("khu du lịch", "danh thắng", "quần thể", "di tích", "văn miếu")


def sight_like(place):
    """A landmark-search hit tagged only building=yes counts when its name says it is a sight."""
    if place.types != ["building"]:
        return True
    name = place.name.casefold() + " "
    return any(word in name for word in SIGHT_AREA_WORDS + HERITAGE_WORDS)


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
                location, note = await self.pick_locality(destination, exc.choices)
                notes.append(note)
            self._localities[key] = (time.monotonic(), location, notes)
            return location, list(notes)

    async def pick_locality(self, destination, choices):
        """Choose among ambiguous matches: for a province name, its city, never a namesake village.

        "Ninh Bình" matches villages in Đà Nẵng and Khánh Hòa while the provincial city is now
        named Hoa Lư, so the first match would put the search in the wrong province.
        """
        catalog = load_catalog()
        regions = [r for r in catalog.matches(destination) if not r["historical"]]
        if len(regions) == 1:
            region = regions[0]
            inside = sorted(
                (p for p in choices if catalog.contains(region["id"], p.longitude, p.latitude)), key=city_rank
            )
            if not inside or city_rank(inside[0]) == len(CITY_CODES):
                try:
                    seat = await self.geo.province_seat(destination)
                except (AgentError, TimeoutError):
                    seat = None
                if seat is not None:
                    return seat, (
                        f"“{destination}” là tên tỉnh; đang tìm quanh {seat.name}, {region['label']}. "
                        "Ghi rõ thành phố/xã nếu bạn muốn nơi khác trong tỉnh."
                    )
            if inside:
                choices = inside + [p for p in choices if p not in inside]
        if not choices:
            raise AgentError(f"Không tìm thấy địa danh “{destination}” ở Việt Nam")
        location = choices[0]
        where = ", ".join(part for part in [location.name, location.admin1] if part)
        return location, (
            f"“{destination}” khớp {len(choices)} địa danh; đang dùng {where}. "
            "Ghi rõ tỉnh/thành nếu đây không phải nơi bạn muốn."
        )

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
        # Heritage-listed landmarks (Văn Miếu – Quốc Tử Giám) come first: Photon cannot find
        # them by tag. Both lookups are optional extras; the main lists stand on their own.
        landmarks = await self.landmarks(location, self.heritage_radius_m)
        try:
            found, _, _ = await self.geo.discover(location, "heritage", self.heritage_radius_m)
        except AgentError:
            found = []
        taken = {name_key(p) for p in already}
        landmarks = [p for p in unique_plausible(landmarks) if name_key(p) not in taken]
        taken |= {name_key(p) for p in landmarks}
        fresh = [p for p in unique_plausible(found) if name_key(p) not in taken]
        # Named sites ("Lăng Tự Đức") before unnamed-looking ones; distance order within each.
        fresh.sort(key=lambda p: not any(w in p.name.casefold() + " " for w in HERITAGE_WORDS))
        return (landmarks[: (self.heritage + 1) // 2] + fresh)[: self.heritage]

    async def landmarks(self, location, radius_m, keyword=""):
        """Overpass landmarks, or nothing when that source is down (it only adds to Photon)."""
        try:
            return await self.geo.landmarks(location, radius_m, keyword)
        except (AgentError, TimeoutError):
            return []

    async def search_places(self, query):
        location, warnings = await self.locate(query.destination)
        found, _, _ = await self.geo.discover(location, query.category, query.radius_m, query.keyword)
        keyword = query.keyword.strip()
        if keyword:
            # Photon also returns loose fuzzy hits ("chùa" → "Phan Bội Châu"): keep only places whose
            # name contains the keyword (accents aside; keyword_filter checks accents below).
            found = [p for p in found if keyword_matches(p, keyword) or loosely_named(p, keyword)]
            english = KEYWORD_ENGLISH.get(" ".join(words(keyword)))
            if english:  # OSM names are often English ("Vegetarian restaurant")
                try:
                    more, _, _ = await self.geo.discover(location, query.category, query.radius_m, english)
                except AgentError:
                    more = []
                found += [p for p in more if keyword_matches(p, english) or loosely_named(p, english)]
            # Photon's keyword search returns few, fuzzy hits; also match the keyword against the
            # nearby list (and historic sites for sights) by name or type, accents included.
            extra = []
            for category, radius in [(query.category, query.radius_m)] + (
                    [("heritage", self.heritage_radius_m)] if query.category == "attraction" else []):
                try:
                    nearby, _, _ = await self.geo.discover(location, category, radius)
                except AgentError:
                    continue
                extra += [p for p in nearby if keyword_matches(p, query.keyword)]
            if query.category == "attraction":
                # A keyword usually names one landmark, and landmarks often lie outside the
                # default 3 km (Ngũ Hành Sơn ~8 km, Tràng An ~6 km from the centre).
                radius = max(query.radius_m, self.heritage_radius_m)
                landmarks = await self.landmarks(location, radius, keyword)
                try:
                    named, _, _ = await self.geo.discover(location, "landmark", radius, keyword)
                except (AgentError, TimeoutError):
                    named = []
                named = [p for p in named if loosely_named(p, keyword) and sight_like(p)]
                # The site itself before its gate building or a namesake park (distance order kept).
                landmarks += sorted(named, key=attraction_rank)
                ids = set()
                landmarks = [p for p in landmarks if p.id not in ids and not ids.add(p.id)]
                found = landmarks + [p for p in found if p.id not in ids]
            seen = {p.id for p in found}
            found = found + [p for p in extra if p.id not in seen and not seen.add(p.id)]
            found = keyword_filter(found, query.keyword)
            found.sort(key=lambda p: not keyword_matches(p, query.keyword))
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


def words(text):
    return re.findall(r"\w+", unicodedata.normalize("NFC", text.casefold()))


# Keywords that name a kind of place rather than words in its name.
KEYWORD_TYPES = {
    "lăng": {"tomb"}, "lăng tẩm": {"tomb"}, "tomb": {"tomb"}, "mộ": {"tomb"},
    "chùa": {"temple", "place_of_worship", "buddhist"}, "đền": {"temple"}, "temple": {"temple"},
    "pagoda": {"temple", "buddhist"}, "bảo tàng": {"museum"}, "museum": {"museum"},
    "chay": {"vegetarian", "vegan"}, "vegetarian": {"vegetarian", "vegan"}, "vegan": {"vegan"},
    "hải sản": {"seafood"}, "seafood": {"seafood"}, "biển": {"beach"}, "beach": {"beach"},
    "công viên": {"park"}, "park": {"park"}, "cà phê": {"cafe"}, "cafe": {"cafe"}, "chợ": {"marketplace"},
}


KEYWORD_ENGLISH = {"chay": "vegetarian", "đồ chay": "vegetarian", "hải sản": "seafood", "lăng": "tomb",
                   "chùa": "pagoda", "bảo tàng": "museum", "chợ": "market", "biển": "beach"}


def keyword_matches(place, keyword):
    """Name contains the keyword with the same accents, or the place's type is what the keyword names."""
    wanted = words(keyword)
    name = words(place.name)
    if wanted and any(name[i:i + len(wanted)] == wanted for i in range(len(name))):
        return True
    kinds = KEYWORD_TYPES.get(" ".join(wanted), set())
    return bool(kinds & {t.casefold() for t in place.types})


def loosely_named(place, keyword):
    """The keyword's words appear in the name, ignoring accents ("pho" in "Phở Quân", not in "Phong")."""
    wanted = [plain(w) for w in words(keyword)]
    name = [plain(w) for w in words(place.name)]
    return bool(wanted) and any(name[i:i + len(wanted)] == wanted for i in range(len(name)))


def keyword_filter(places, keyword):
    """Drop fuzzy matches that only agree once diacritics are removed.

    Photon ignores Vietnamese diacritics, so "lăng" (tomb) also finds "Làng" (village) and
    "chay" (vegetarian) finds "cháy" (burnt). A place whose name contains the keyword only
    in such a different-diacritics form is dropped when the keyword itself has diacritics, or
    when other places match it exactly. Places matched through other fields are kept.
    """
    wanted = words(keyword)
    if not wanted:
        return places
    plain_wanted = [plain(w) for w in wanted]

    def exact(place):
        name = words(place.name)
        return any(name[i:i + len(wanted)] == wanted for i in range(len(name)))

    def conflict(place):
        name = words(place.name)
        flat = [plain(w) for w in name]
        fuzzy = any(flat[i:i + len(wanted)] == plain_wanted for i in range(len(flat)))
        return fuzzy and not exact(place)

    has_marks = any(w != plain(w) for w in wanted)
    if has_marks or any(exact(p) for p in places):
        return [p for p in places if not conflict(p)]
    return places
