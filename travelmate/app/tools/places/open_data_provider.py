"""Keyless live provider for the itinerary API.

Places come from Photon/OpenStreetMap around a GeoNames/Open-Meteo locality, weather
from the Open-Meteo forecast. No API key is needed; only the LLM planner needs one.
Coverage is community data, not an exhaustive or verified list, and the responses
say so.
"""

# Nguồn địa điểm miễn phí đang chạy trên Render (không cần khoá API). Một lần tìm cho một chuyến đi:
# 1. locate(): đổi tên điểm đến thành toạ độ (có thử bỏ chữ thừa và sửa lỗi gõ).
# 2. Photon: điểm tham quan và quán ăn quanh trung tâm; Photon lỗi thì lấy điểm tham quan từ Wikipedia.
# 3. Overpass: di tích, lăng tẩm ở xa trung tâm hơn (chạy song song với bước 2).
# 4. Nơi ở gần đó, rồi ảnh cho tất cả, rồi giá vé từ bảng có nguồn.

import asyncio
import logging
import re
import time
import unicodedata
from datetime import date, timedelta

import httpx

from app.core.base import AgentError, UserError
from app.core.models import Context, PlaceResult, WeatherDay, WeatherResult
from app.tools.places.destination_names import cleaned, closest
from app.tools.places.geo_places import GeoPlaceService, LocalityChoiceRequired
from app.tools.places.place_media import WikipediaImages, plain
from app.tools.places.vietnam_regions import load_catalog
from app.tools.places.wiki_places import WikipediaPlaces
from app.tools.prices.ticket_prices import apply_tickets
from app.tools.weather_history import WeatherHistory
from app.tools.weather_met import MetNorway

# Cảnh báo ghi nguồn OpenStreetMap (bắt buộc theo giấy phép ODbL).
logger = logging.getLogger(__name__)

SOURCE_NOTE = (
    "Địa điểm từ OpenStreetMap qua Photon (dữ liệu cộng đồng, ODbL); có thể thiếu hoặc cũ, "
    "chưa xác minh giờ mở cửa, giá hay tình trạng hoạt động."
)
WIKI_NOTE = (
    "Bản đồ OpenStreetMap (Photon) đang quá tải nên điểm tham quan được lấy từ Wikipedia tiếng Việt; "
    "lần này có thể thiếu gợi ý quán ăn và nơi ở. Thử lại sau ít phút để có danh sách đầy đủ."
)
# Kết quả xác định điểm đến được nhớ 10 phút (tìm địa điểm và thời tiết dùng chung).
LOCALITY_TTL_S = 600


# Không có nơi nào ở Việt Nam khớp tên người dùng nhập.
class DestinationNotFound(UserError):
    """No place in Vietnam matches what the traveller typed."""


# Lower ranks first. Within a rank the source's distance order is kept, so landmarks beat
# the nearest park or statue without leaving the search radius.
# Thứ hạng loại điểm tham quan: số nhỏ là danh thắng mạnh hơn.
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


# Ưu tiên thành phố/thị xã khi chọn giữa nhiều nơi trùng tên.
def city_rank(locality):
    code = locality.feature_code
    return CITY_CODES.index(code) if code in CITY_CODES else len(CITY_CODES)


# Bỏ bản ghi OSM có tên là ghi chú hoặc mẩu tên, không phải tên địa điểm.
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


# Bỏ tên rác và tên trùng.
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


# Danh thắng trước, tên có chữ di tích (lăng, chùa, đền...) trước, 'trung tâm' sau cùng.
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


# Chọn điểm tham quan: danh thắng trước, nhưng không để một loại (ví dụ bảo tàng) chiếm hết danh sách; công
# viên có giới hạn riêng.
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


# Chọn quán ăn (bữa chính) và quán cà phê theo số lượng cho mỗi loại.
def pick_food(places, meals, cafes):
    places = unique_plausible(places)
    meal = [p for p in places if MEAL_TYPES & set(p.types)][:meals]
    cafe = [p for p in places if "cafe" in p.types and p not in meal][:cafes]
    return meal + cafe


# Có cùng các hàm như các nguồn khác: search(trip), forecast(trip), search_places(query); agent không cần
# biết đang dùng nguồn nào.
class OpenDataProvider:
    """Implements search(trip), forecast(trip) and search_places(query) like the other providers."""

    def __init__(
        self, geo=None, weather=None, radius_m=5000, attractions=12, meals=5, cafes=2, max_parks=2,
        heritage_radius_m=15000, heritage=8, stays=5, images=None, wiki=None, history=None, backup_weather=None,
        contact="",
    ):
        self.geo = geo or GeoPlaceService()
        self.weather = weather  # a WeatherSpecialist; created lazily
        self.radius_m = radius_m
        self.heritage_radius_m, self.heritage = heritage_radius_m, heritage
        self.stay_limit = stays
        self.images = images if images is not None else WikipediaImages()
        # Sights when Photon is down (it often is: a free public server); False turns it off.
        self.wiki = wiki if wiki is not None else WikipediaPlaces()
        # Past years' weather for trip days beyond the 16-day forecast; False turns it off.
        self.history = history if history is not None else WeatherHistory()
        # Forecast from MET Norway when Open-Meteo fails (it limits shared cloud IPs); False turns it off.
        # contact: the site's public address, which MET asks every request to carry.
        self.backup_weather = backup_weather if backup_weather is not None else MetNorway(contact)
        self.pickers = {
            "attraction": lambda found: pick_attractions(found, attractions, max_parks),
            "restaurant": lambda found: pick_food(found, meals, cafes),
        }
        self._localities = {}
        self._lock = asyncio.Lock()

    # Có khoá (lock) để nhiều yêu cầu cùng lúc không tra cùng một tên nhiều lần.
    async def locate(self, destination):
        """Resolve a destination to one locality, picking the top match when ambiguous.

        A name the map search does not know is tried again without extra words ("Hạ Long Bay")
        and then as the well-known destination it is almost spelled as ("Đà Lạtt"). Errors are
        UserErrors written for the traveller: not found (what to change), or the map is busy.
        """
        key = destination.casefold().strip()
        async with self._lock:
            cached = self._localities.get(key)
            if cached and time.monotonic() - cached[0] < LOCALITY_TTL_S:
                return cached[1], list(cached[2])
            try:
                location, notes = await self.resolve_destination(destination)
            except UserError:
                raise
            except (AgentError, TimeoutError) as exc:  # the map sources are down or too slow
                raise UserError(f"Máy chủ bản đồ đang bận nên chưa tìm được “{destination}”. "
                                "Vui lòng thử lại sau ít phút.") from exc
            self._localities[key] = (time.monotonic(), location, notes)
            return location, list(notes)

    # Thử lần lượt: tên gốc -> tên bỏ chữ thừa -> tên nổi tiếng gần giống.
    async def resolve_destination(self, destination):
        """(locality, notes) for what the traveller typed, trying the second guesses in order."""
        try:
            return await self.resolve_one(destination)
        except DestinationNotFound:
            pass
        shorter = cleaned(destination)
        if shorter:
            try:
                return await self.resolve_one(shorter)
            except DestinationNotFound:
                pass
        guess = closest(shorter or destination)
        if guess:
            try:
                location, notes = await self.resolve_one(guess)
            except DestinationNotFound:
                pass
            else:
                note = f"Không tìm thấy “{destination}”; đang dùng “{guess}”. Sửa lại nếu đây không phải nơi bạn muốn."
                return location, [note, *notes]
        raise DestinationNotFound(
            f"Không tìm thấy địa danh “{destination}” ở Việt Nam. Kiểm tra lại chính tả, hoặc ghi tên thành phố "
            "hay tỉnh, ví dụ “Đà Lạt”, “Hạ Long”. TravelMate hiện chỉ lập lịch cho điểm đến trong Việt Nam."
        )

    # Tên khớp nhiều nơi thì chọn nơi phù hợp nhất và ghi chú cho người dùng.
    async def resolve_one(self, destination):
        try:
            return await self.geo.resolve(destination, None, "nearby"), []
        except LocalityChoiceRequired as exc:
            location, note = await self.pick_locality(destination, exc.choices)
            return location, [note]

    # Chọn giữa nhiều nơi trùng tên; với tên tỉnh thì lấy thành phố của tỉnh đó.
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
            raise DestinationNotFound(f"Không tìm thấy địa danh “{destination}” ở Việt Nam")
        location = choices[0]
        where = ", ".join(part for part in [location.name, location.admin1] if part)
        return location, (
            f"“{destination}” khớp {len(choices)} địa danh; đang dùng {where}. "
            "Ghi rõ tỉnh/thành nếu đây không phải nơi bạn muốn."
        )

    # Kết quả tìm cho một chuyến đi (bỏ cờ 'đầy đủ').
    async def search(self, trip):
        result, _ = await self.search_cacheable(trip)
        return result

    # Trả thêm cờ 'đầy đủ' để bộ nhớ đệm biết có nên lưu không.
    async def search_cacheable(self, trip):
        """(PlaceResult, complete): complete is False when a source failed and a fallback filled in,
        so a degraded list is not kept for a day (main.CachingProvider)."""
        location, warnings = await self.locate(trip.destination)
        # Overpass is another server: its (often slow) landmark query runs while Photon answers.
        landmarks = asyncio.create_task(self.landmarks(location, self.heritage_radius_m)) if self.heritage else None
        try:
            return await self._search(trip, location, warnings, landmarks)
        finally:
            if landmarks is not None and not landmarks.done():
                landmarks.cancel()

    # Phần thân của việc tìm, theo các bước ở đầu file.
    async def _search(self, trip, location, warnings, landmarks):
        places, failures, from_wiki = [], 0, False
        for category, pick in self.pickers.items():
            try:
                found, _, _ = await self.geo.discover(location, category, self.radius_m)
            except (AgentError, TimeoutError):
                found = await self.wiki.nearby(location, self.heritage_radius_m) if (
                    category == "attraction" and self.wiki) else []
                if not found:
                    failures += 1
                    continue
                from_wiki = True
            places.extend(pick(found))
        # Nearby stays (Photon) are fetched while heritage sites load; then photos for both.
        stays_task = asyncio.create_task(self.stays(location))
        try:
            places.extend(await self.heritage_sites(location, places, landmarks))
        finally:
            stays = await stays_task
        if self.images:  # one pass for both: photos load concurrently within one time budget
            enriched = await self.images.enrich(places + stays)
            places, stays = enriched[:len(places)], enriched[len(places):]
        places = apply_tickets(places, trip.destination)
        if failures == len(self.pickers):
            raise UserError("Nguồn địa điểm không phản hồi. Vui lòng thử lại sau ít phút.")
        if from_wiki:
            warnings.append(WIKI_NOTE)
        elif failures:
            warnings.append("Một nhóm địa điểm không tải được; danh sách có thể thiếu.")
        if not places:
            warnings.append(f"Không thấy địa điểm trong bán kính {self.radius_m // 1000} km quanh trung tâm.")
        from_osm = any(p.source != "wikipedia" for p in places + stays) or not places
        result = PlaceResult(places=places, warnings=warnings + ([SOURCE_NOTE] if from_osm else []), stays=stays)
        landmarks_ok = landmarks is None or (landmarks.done() and landmarks.result() is not None)
        return result, bool(places) and not failures and not from_wiki and landmarks_ok

    # Nơi ở gần đó: chỉ tên và vị trí, không có giá phòng.
    async def stays(self, location):
        """Nearby accommodation from OSM: names and locations only, no nightly prices."""
        if not self.stay_limit:
            return []
        try:
            found, _, _ = await self.geo.discover(location, "hotel", self.radius_m)
        except (AgentError, TimeoutError):
            return []
        return unique_plausible(found)[: self.stay_limit]

    # Lăng tẩm, đền chùa cổ thường nằm xa trung tâm: tìm trong bán kính rộng hơn.
    async def heritage_sites(self, location, already, pending=None):
        """Royal tombs and historic temples often lie outside the city-centre radius.

        pending: the landmark lookup already started by search(), to await instead of a new one.
        """
        if not self.heritage:
            return []
        # Heritage-listed landmarks (Văn Miếu – Quốc Tử Giám) come first: Photon cannot find
        # them by tag. Both lookups are optional extras; the main lists stand on their own.
        try:
            found, _, _ = await self.geo.discover(location, "heritage", self.heritage_radius_m)
        except (AgentError, TimeoutError):
            found = []
        landmarks = (await pending if pending is not None else await self.landmarks(location, self.heritage_radius_m)) or []
        taken = {name_key(p) for p in already}
        landmarks = [p for p in unique_plausible(landmarks) if name_key(p) not in taken]
        taken |= {name_key(p) for p in landmarks}
        fresh = [p for p in unique_plausible(found) if name_key(p) not in taken]
        # Named sites ("Lăng Tự Đức") before unnamed-looking ones; distance order within each.
        fresh.sort(key=lambda p: not any(w in p.name.casefold() + " " for w in HERITAGE_WORDS))
        return (landmarks[: (self.heritage + 1) // 2] + fresh)[: self.heritage]

    # Danh thắng từ Overpass; Overpass lỗi thì trả None (nó chỉ bổ sung cho Photon, không bắt buộc).
    async def landmarks(self, location, radius_m, keyword=""):
        """Overpass landmarks, or None when that source is down (it only adds to Photon)."""
        try:
            return await self.geo.landmarks(location, radius_m, keyword)
        except (AgentError, TimeoutError):
            return None

    # Tìm theo từ khoá (trang Khám phá, chat, Planning Agent). Photon tìm mờ nên kết quả được lọc lại theo
    # tên, có xét dấu tiếng Việt.
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
                landmarks = await self.landmarks(location, radius, keyword) or []
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
        found = unique_plausible(found)[: query.limit]
        # Places found for a stated wish ("mì Quảng") are often the ones a plan leads with: give them photos too.
        found = await self.images.enrich(found) if self.images else found
        return PlaceResult(places=found, warnings=warnings + [SOURCE_NOTE])

    # Dự báo thời tiết cho từng ngày của chuyến đi: Open-Meteo; lỗi thì MET Norway; ngày quá xa thì thời
    # tiết cùng kỳ các năm trước (chỉ để tham khảo).
    async def forecast(self, trip):
        from app.specialists.weather import WeatherRequest, WeatherSpecialist

        location, _ = await self.locate(trip.destination)
        weather = self.weather or WeatherSpecialist()
        requested = [trip.start_date + timedelta(days=i) for i in range((trip.end_date - trip.start_date).days + 1)]
        try:
            report = await weather.run(
                WeatherRequest(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    start_date=trip.start_date,
                    end_date=trip.end_date,
                ),
                Context(),
            )
        except (AgentError, TimeoutError) as exc:
            # Keep why (HTTP status, timeout) in the log: a shared server IP being limited looks like this.
            logger.warning("weather source=open-meteo outcome=failed error_type=%s detail=%s", type(exc).__name__,
                           str(exc)[:120])
            if not self.backup_weather:
                raise
            return await self.backup_forecast(location, requested)
        days = [WeatherDay(date=d.date, weather_code=d.weather_code) for d in report.days if d.weather_code is not None]
        # "not_flagged" is the specialist's own label, not something to show travellers.
        warnings = [w for w in report.warnings if "not_flagged" not in w]
        for d in report.days:
            if d.outdoor_risk == "elevated":
                chance = f" ({d.precipitation_probability}% khả năng mưa)" if d.precipitation_probability is not None else ""
                warnings.append(f"{d.date.isoformat()}: thời tiết có thể không thuận cho hoạt động ngoài trời{chance}.")
        typical, note = await self.past_years(location, report.missing_dates, horizon_days=15, source="Open-Meteo",
                                              horizon="16 ngày")
        warnings += note
        return WeatherResult(days=days, warnings=warnings + ["Thời tiết: dự báo Open-Meteo."], typical=typical)

    async def backup_forecast(self, location, requested):
        """Forecast from MET Norway after Open-Meteo failed; raises when both are down."""
        try:
            met = await self.backup_weather.daily(location.latitude, location.longitude)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.warning("weather source=met-norway outcome=failed error_type=%s", type(exc).__name__)
            raise AgentError("Both weather sources failed") from exc
        found = [met[d] for d in requested if d in met]
        days = [WeatherDay(date=d.date, weather_code=d.weather_code) for d in found]
        warnings = ["Nguồn MET Norway (Viện Khí tượng Na Uy), vì Open-Meteo không trả lời. Dự báo có thể thay đổi; "
                    "không phải cảnh báo thời tiết chính thức."]
        for d in found:
            if d.elevated:
                rain = f" (tới {d.rain_mm:g} mm mưa trong 6 giờ)" if d.rain_mm else ""
                warnings.append(f"{d.date.isoformat()}: thời tiết có thể không thuận cho hoạt động ngoài trời{rain}.")
        missing = [d for d in requested if d not in met]
        typical, note = await self.past_years(location, missing, horizon_days=8, source="MET Norway",
                                              horizon="khoảng 10 ngày")
        return WeatherResult(days=days, warnings=warnings + note + ["Thời tiết: dự báo MET Norway."], typical=typical)

    async def past_years(self, location, missing, horizon_days, source, horizon):
        """(typical weather, notes) for days without a forecast: past years' weather, and why there is none."""
        if not missing:
            return [], []
        typical = await self.history.typical(location.latitude, location.longitude, missing) if self.history else []
        dates = ", ".join(day.strftime("%d/%m") for day in missing)
        reason = f" ({source} chỉ dự báo {horizon} tới)" if min(missing) > date.today() + timedelta(days=horizon_days) else ""
        note = " Lịch hiện thời tiết cùng kỳ các năm trước để tham khảo, không phải dự báo." if typical else ""
        return typical, [f"Chưa có dự báo cho {dates}{reason}.{note}"]


# Các từ của một chuỗi, viết thường.
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


# Tên chứa đúng từ khoá (cùng dấu), hoặc loại địa điểm đúng là thứ từ khoá nói tới.
def keyword_matches(place, keyword):
    """Name contains the keyword with the same accents, or the place's type is what the keyword names."""
    wanted = words(keyword)
    name = words(place.name)
    if wanted and any(name[i:i + len(wanted)] == wanted for i in range(len(name))):
        return True
    kinds = KEYWORD_TYPES.get(" ".join(wanted), set())
    return bool(kinds & {t.casefold() for t in place.types})


# Tên chứa các từ của từ khoá, bỏ qua dấu.
def loosely_named(place, keyword):
    """The keyword's words appear in the name, ignoring accents ("pho" in "Phở Quân", not in "Phong")."""
    wanted = [plain(w) for w in words(keyword)]
    name = [plain(w) for w in words(place.name)]
    return bool(wanted) and any(name[i:i + len(wanted)] == wanted for i in range(len(name)))


# Bỏ kết quả chỉ khớp khi bỏ dấu ('phở' không khớp 'phố').
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
