"""Vietnam locality resolution and bounded multi-category OSM POI discovery.

GeoNames/Open-Meteo resolves populated places. Photon supplies OSM features;
no public Nominatim dependency and no locality centre substituted for a POI.
"""

import asyncio
import json
import math
import re
import time
import unicodedata
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from pydantic import Field

from app.core.base import AgentError
from app.core.models import Model, Place
from app.tools.places.osm_places import ATTRIBUTION, distance_m, normalized, safe_web_url
from app.tools.places.vietnam_regions import load_catalog, name_key

TAGS = {
    "hotel": {
        "tourism:hotel",
        "tourism:hostel",
        "tourism:guest_house",
        "tourism:resort",
        "tourism:motel",
        "tourism:camp_site",
    },
    "restaurant": {"amenity:restaurant", "amenity:cafe", "amenity:food_court", "amenity:fast_food"},
    # Tombs, historic temples and archaeological sites (e.g. Hue's royal tombs). Kept apart
    # from "attraction" so itinerary search can look for them in a wider radius.
    "heritage": {"historic:tomb", "historic:temple", "historic:archaeological_site"},
    "attraction": {
        "tourism:attraction",
        "tourism:viewpoint",
        "tourism:museum",
        "tourism:gallery",
        "tourism:zoo",
        "tourism:theme_park",
        "tourism:aquarium",
        "natural:beach",
        "natural:cave_entrance",
        "natural:peak",
        "boundary:national_park",
        "historic:monument",
        "historic:memorial",
        "historic:castle",
        "leisure:park",
        "leisure:nature_reserve",
    },
}
# Keyword searches for a named sight. Photon indexes each feature under one tag, often not
# the sight tag: Văn Miếu – Quốc Tử Giám is landuse=religious, Ngũ Hành Sơn natural=wood,
# Tràng An's boat-tour area building=yes. Too broad for a nearby list, but fine once the
# name must contain the keyword (the caller filters by name).
TAGS["landmark"] = TAGS["attraction"] | TAGS["heritage"] | {
    "landuse:religious",
    "amenity:place_of_worship",
    "natural:wood",
    "boundary:protected_area",
    "building:yes",
}
LANDMARK_TYPES = {"religious": "temple", "wood": "attraction", "protected_area": "nature_reserve",
                  "yes": "building"}

# A destination is a settlement or a geographic/tourism landmark, not any
# business with a matching name. In particular hotels and information booths
# must not become the centre of a city search.
DESTINATION_TAGS = {
    "place:city",
    "place:town",
    "place:village",
    "place:hamlet",
    "place:suburb",
    "place:quarter",
    "place:neighbourhood",
    "place:island",
    "place:locality",
    "tourism:attraction",
    "tourism:theme_park",
    "tourism:museum",
    "tourism:viewpoint",
    "natural:peak",
    "natural:beach",
    "natural:cave_entrance",
    "natural:bay",
    "boundary:national_park",
    "leisure:nature_reserve",
    "leisure:park",
    "aerialway:station",
    "historic:monument",
    "historic:castle",
}


# Photon indexes a feature under one tag only, so landmarks whose sight tag is secondary are
# invisible to a tag-filtered Photon search: Văn Miếu – Quốc Tử Giám is landuse=religious +
# heritage=2, Ngũ Hành Sơn is natural=wood + tourism=attraction, and Tràng An's boat-tour
# area is indexed as building=yes. Overpass sees every tag, so landmarks are looked up there.
NOT_SIGHT_TOURISM = (
    "hotel|hostel|guest_house|motel|apartment|camp_site|caravan_site|chalet|information|"
    "picnic_site|alpine_hut|wilderness_hut"
)
NOT_SIGHT_KEYS = ("highway", "railway", "public_transport", "place", "shop", "office")
VIETNAMESE_LETTERS = (
    "aàáảãạăằắẳẵặâầấẩẫậeèéẻẽẹêềếểễệiìíỉĩịoòóỏõọôồốổỗộơờớởỡợuùúủũụưừứửữựyỳýỷỹỵdđ"
)


def name_pattern(keyword):
    """Overpass regex for the keyword's words in a name, as alternations (byte-safe for UTF-8).

    A keyword typed with diacritics must match them exactly ("lăng" is not "làng"); one typed
    without them ("van mieu") matches any accented form. The first letter of each word may
    also be a capital, as Vietnamese place names are written.
    """
    parts = []
    keyword = unicodedata.normalize("NFC", keyword.casefold())
    marked = normalized(keyword) != " ".join(keyword.split())
    for word in re.findall(r"[^\W_]+", keyword):
        letters = []
        for i, ch in enumerate(word):
            if not marked and ch in VIETNAMESE_LETTERS:  # unaccented keyword: any accented form
                forms = {v for v in VIETNAMESE_LETTERS if normalized(v) == ch}
            else:  # a keyword with diacritics matches them exactly
                forms = {ch}
            if i == 0:
                forms |= {f.upper() for f in forms}
            letters.append(forms.pop() if len(forms) == 1 else "(" + "|".join(sorted(forms)) + ")")
        parts.append("".join(letters))
    return " +".join(parts)


def landmark_kind(tags):
    """The place type used for ranking: the sight tag, not whichever tag Photon would pick."""
    if tags.get("tourism") and tags["tourism"] != "yes":
        return tags["tourism"]
    if tags.get("historic") and tags["historic"] != "yes":
        return tags["historic"]
    if tags.get("amenity") == "place_of_worship" or tags.get("landuse") == "religious":
        return "temple"
    if tags.get("natural") in {"peak", "cave_entrance", "beach"}:
        return tags["natural"]
    return "attraction"


def relevant_name(query, candidate):
    """Reject fuzzy search noise; aliases affect names only, never coordinates."""
    wanted, actual = name_key(query.split(",")[0]), name_key(candidate)
    if not wanted or not actual:
        return False
    aliases = {"fansipan", "phanxipang", "phanxiphang", "phansipang"}
    names = aliases if wanted in aliases else {wanted}
    return any(name in actual for name in names)


class Locality(Model):
    id: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    admin1: str = ""
    admin2: str = ""
    feature_code: str
    country_code: str = "VN"
    source_url: str
    fetched_at: datetime
    scope: str = "nearby"
    bbox: list[float] | None = None
    boundary_version: str | None = None
    historical: bool = False
    attribution: str | None = None
    coordinate_kind: str = "reference_point"


class LocalityChoiceRequired(AgentError):
    def __init__(self, choices, reason):
        self.choices, self.reason = choices, reason
        super().__init__(reason)


class PlaceMetadata(Model):
    distance_m: float = Field(ge=0)
    address_precision: str
    retrieval_url: str
    cache_hit: bool
    phone: str | None = None
    coverage_partial: bool = False
    spatial_filter: str = "radius"
    secondary_sources: list[str] = Field(default_factory=list)


class PublicGeoClient:
    """Single-process bounded cache, coalescing and rate limit for public services."""

    def __init__(self, *, transport=None, interval=1.1):
        self.transport, self.interval = transport, interval
        self._lock = asyncio.Lock()
        self._cache = {}
        self._last = 0.0
        self._cooldown = {}

    async def get(self, url, params, ttl=300):
        params = tuple(sorted(params))
        key = (url, params)
        async with self._lock:
            now = time.monotonic()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if key in self._cache:
                _, payload, stamp = self._cache[key]
                return deepcopy(payload), stamp, True, url + "?" + urlencode(params)
            host = httpx.URL(url).host
            if self._cooldown.get(host, 0) > now:
                raise AgentError("Source cooldown active")
            await asyncio.sleep(max(0, self.interval - (now - self._last)))
            self._last = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=15,
                    follow_redirects=False,
                    headers={"User-Agent": "TravelMateResearch/0.3", "Accept": "application/json"},
                ) as client:
                    async with client.stream("GET", url, params=list(params)) as response:
                        if response.status_code == 429:
                            retry = response.headers.get("Retry-After", "30")
                            seconds = min(3600, max(30, int(retry))) if retry.isdigit() else 30
                            self._cooldown[host] = time.monotonic() + seconds
                        elif response.status_code in {502, 503, 504}:
                            # An overloaded server (public Overpass at capacity): fail fast for
                            # a while instead of making every search wait on it again.
                            self._cooldown[host] = time.monotonic() + 60
                        response.raise_for_status()
                        content = bytearray()
                        async for part in response.aiter_bytes():
                            content.extend(part)
                            if len(content) > 1_000_000:
                                raise ValueError("Source response too large")
                payload = json.loads(content)
                if not isinstance(payload, dict) or payload.get("error"):
                    raise ValueError("Invalid source payload")
            except httpx.TimeoutException:
                raise TimeoutError("Geographic source timed out") from None
            except (httpx.HTTPError, ValueError, TypeError):
                raise AgentError("Geographic source unavailable or invalid") from None
            stamp = datetime.now(UTC)
            if len(self._cache) >= 128:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + ttl, deepcopy(payload), stamp)
            return payload, stamp, False, url + "?" + urlencode(params)


class GeoPlaceService:
    def __init__(
        self,
        client=None,
        photon_url="https://photon.komoot.io",
        geocoding_url="https://geocoding-api.open-meteo.com/v1/search",
        overpass_url="https://overpass-api.de/api/interpreter",
    ):
        self.client = client or PublicGeoClient()
        self.photon_url = photon_url.rstrip("/")
        self.geocoding_url = geocoding_url
        self.overpass_url = overpass_url

    async def landmarks(self, location, radius_m, keyword=""):
        """Named sights around a locality from Overpass, nearest first.

        With a keyword: sights (tourism, historic or heritage tag) whose name contains it.
        Without one: heritage-listed sites and Wikidata-linked attractions, the closest thing
        OSM has to "well-known", ordered by heritage level (1 = UNESCO) and then distance.
        The public Overpass server is often at capacity; callers treat this as optional.
        """
        around = f"(around:{int(radius_m)},{location.latitude:.6f},{location.longitude:.6f})"
        if keyword:
            pattern = name_pattern(keyword)
            if not pattern:
                return []
            body = (
                f'(nwr{around}["tourism"]["tourism"!~"^({NOT_SIGHT_TOURISM})$"];'
                f'nwr{around}["historic"];nwr{around}["heritage"];)->.s;'
                f'nwr.s["name"~{json.dumps(pattern, ensure_ascii=False)}];'
            )
        else:
            # Only UNESCO (1) and national (2) heritage: lower levels include heritage trees.
            body = (
                f'(nwr{around}["name"]["heritage"~"^[12]$"];'
                f'nwr{around}["name"]["tourism"="attraction"]["wikidata"];);'
            )
        query = f"[out:json][timeout:12];{body}out tags center 150;"
        payload, stamp, _, _ = await self.client.get(self.overpass_url, [("data", query)], ttl=3600)
        elements = payload.get("elements")
        if payload.get("remark") or not isinstance(elements, list) or len(elements) > 150:
            raise AgentError("Overpass reported partial results or an invalid payload")
        found = []
        for item in elements:
            try:
                place, distance, level = self.parse_landmark(item, location, radius_m, stamp)
            except (KeyError, TypeError, ValueError):
                continue
            if place is not None:
                found.append((level if not keyword else 0, distance, place))
        found.sort(key=lambda row: (row[0], row[1], row[2].id))
        seen, out = set(), []
        for _, _, place in found:
            if normalized(place.name) not in seen:
                seen.add(normalized(place.name))
                out.append(place)
        return out

    def parse_landmark(self, item, location, radius_m, stamp):
        tags = item.get("tags") or {}
        name = tags.get("name")
        if not isinstance(name, str) or not name.strip() or any(k in tags for k in NOT_SIGHT_KEYS):
            return None, 0, 0
        if tags.get("boundary") in {"administrative", "historic"} or tags.get("amenity") in {
            "school", "police", "townhall", "hospital", "parking", "restaurant", "cafe",
        }:
            return None, 0, 0
        kind = item["type"]
        if kind == "node":
            lat, lon = item["lat"], item["lon"]
        else:
            lat, lon = item["center"]["lat"], item["center"]["lon"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in [lat, lon]):
            raise ValueError("Coordinates must be numbers")
        identity = item["id"]
        if kind not in {"node", "way", "relation"} or type(identity) is not int or identity <= 0:
            raise ValueError("Invalid OSM identity")
        distance = distance_m((location.latitude, location.longitude), (lat, lon))
        if distance > radius_m:
            return None, 0, 0
        url = f"https://www.openstreetmap.org/{kind}/{identity}"
        level = tags.get("heritage", "")
        level = int(level) if level.isdigit() else 8 if level else 9
        address = ", ".join(
            dict.fromkeys(tags[k].strip() for k in ["addr:street", "addr:city"] if isinstance(tags.get(k), str))
        )
        opening = tags.get("opening_hours") if isinstance(tags.get("opening_hours"), str) else None
        try:
            website = safe_web_url(tags.get("website") or tags.get("contact:website"))
        except ValueError:
            website = None
        place = Place(
            id=f"osm:{kind}/{identity}",
            name=name.strip(),
            address=address,
            latitude=lat,
            longitude=lon,
            source="osm_overpass",
            source_url=url,
            attribution=ATTRIBUTION,
            fetched_at=stamp,
            types=[landmark_kind(tags)],
            coordinate_kind="point" if kind == "node" else "geometry_center",
            website_url=website,
            opening_hours_raw=opening,
            field_sources={field: url for field in ["name", "latitude", "longitude", "types"]}
            | ({"address": url} if address else {})
            | ({"website_url": url} if website else {})
            | ({"opening_hours_raw": url} if opening else {}),
        )
        return place, distance, level

    async def province_seat(self, destination):
        """A city inside the current province named by the destination, or None.

        GeoNames still lists "Ninh Bình" as villages in other provinces while the provincial
        city itself is now called Hoa Lư (2025 merger), so a province name alone can resolve
        to a village hundreds of kilometres away. This looks for a city/town within the
        province's reference polygon instead.
        """
        catalog = load_catalog()
        regions = [r for r in catalog.matches(destination) if not r["historical"]]
        if len(regions) != 1:
            return None
        region = regions[0]
        payload, stamp, _, _ = await self.client.get(
            self.photon_url + "/api/",
            [
                ("q", region["name"]),
                ("countrycode", "VN"),
                ("limit", "20"),
                ("bbox", ",".join(map(str, region["bbox"]))),
                ("include", "osm.place.city,osm.place.town"),
            ],
            ttl=600,
        )
        features = payload.get("features")
        if not isinstance(features, list) or len(features) > 100:
            raise AgentError("Invalid locality results")
        seats = []
        for feature in features:
            try:
                props, geometry = feature["properties"], feature["geometry"]
                if props.get("osm_key") != "place" or props.get("osm_value") not in {"city", "town"}:
                    continue
                lon, lat = geometry["coordinates"]
                name, identity = props["name"], props["osm_id"]
                kind = {"N": "node", "W": "way", "R": "relation"}[props["osm_type"]]
                if not isinstance(name, str) or type(identity) is not int or identity <= 0:
                    continue
                if not catalog.contains(region["id"], lon, lat):
                    continue
                seats.append(Locality(
                    id=f"photon:{kind}/{identity}",
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    admin1=region["label"],
                    feature_code="OSM:" + props["osm_value"],
                    source_url=f"https://www.openstreetmap.org/{kind}/{identity}",
                    fetched_at=stamp,
                    coordinate_kind="point" if kind == "node" else "geometry_center",
                ))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        seats.sort(key=lambda p: p.feature_code != "OSM:city")  # cities before towns, Photon order kept
        return seats[0] if seats else None

    def region_location(self, region):
        return Locality(
            id=region["id"],
            name=region["label"],
            latitude=region["center"][1],
            longitude=region["center"][0],
            feature_code="ADM1" if region["id"] != "vn:country" else "ADM0",
            source_url=region["source_url"],
            fetched_at=load_catalog().acquired_at,
            scope="country" if region["id"] == "vn:country" else "area",
            bbox=region["bbox"],
            boundary_version=region["version"],
            historical=region["historical"],
            attribution=region["attribution"],
        )

    async def resolve(self, destination, selected_id=None, search_scope="auto"):
        catalog = load_catalog()
        if search_scope == "country" or (
            search_scope == "auto" and name_key(destination) in {"vietnam", "vn"}
        ):
            if selected_id not in {None, "vn:country"}:
                raise LocalityChoiceRequired([], "Địa danh đã chọn không thuộc phạm vi cả nước.")
            return self.region_location(catalog.country())
        regions = catalog.matches(destination) if search_scope != "nearby" else []
        if regions or search_scope == "area":
            choices = [self.region_location(r) for r in regions]
            if selected_id:
                found = [p for p in choices if p.id == selected_id]
                if len(found) == 1:
                    return found[0]
            raise LocalityChoiceRequired(
                choices,
                "Chọn phạm vi tỉnh/thành. Khu vực cũ có nhãn năm ranh giới; không tự chuyển sang tỉnh mới."
                if choices
                else "Chưa khớp tên tỉnh/thành trong danh mục. Thử tên đầy đủ hoặc chọn tìm quanh địa danh.",
            )
        geo_failed = False
        try:
            payload, stamp, _, _ = await self.client.get(
                self.geocoding_url,
                [
                    ("name", destination.split(",")[0].strip()),
                    ("count", "20"),
                    ("language", "vi"),
                    ("format", "json"),
                    ("countryCode", "VN"),
                ],
                ttl=600,
            )
        except (AgentError, TimeoutError):
            geo_failed = True
            payload, stamp = {"results": []}, datetime.now(UTC)
        raw = payload.get("results", [])
        if not isinstance(raw, list) or len(raw) > 20:
            raise AgentError("Invalid locality results")
        choices = {}
        has_administrative_match = False
        key = normalized(destination.split(",")[0]).replace(" ", "")
        for item in raw:
            try:
                if item["country_code"] != "VN" or type(item["id"]) is not int or item["id"] <= 0:
                    continue
                code = item["feature_code"]
                if not isinstance(code, str) or not isinstance(item.get("name"), str):
                    continue
                if code.startswith("ADM") and normalized(item["name"]).replace(" ", "") == key:
                    has_administrative_match = True
                if not code.startswith("PPL"):
                    continue
                if not relevant_name(destination, item["name"]):
                    continue
                qualifiers = [normalized(v.strip()) for v in destination.split(",")[1:] if v.strip()]
                area = normalized(" ".join(str(item.get(k, "")) for k in ["admin1", "admin2", "admin3"]))
                if any(q not in area for q in qualifiers):
                    continue
                if any(isinstance(item[v], bool) for v in ["latitude", "longitude"]):
                    continue
                place = Locality(
                    id=f"geonames:{item['id']}",
                    name=item["name"],
                    latitude=item["latitude"],
                    longitude=item["longitude"],
                    admin1=item.get("admin1", ""),
                    admin2=item.get("admin2", ""),
                    feature_code=code,
                    source_url=f"https://www.geonames.org/{item['id']}/",
                    fetched_at=stamp,
                )
                choices[place.id] = place
            except (KeyError, TypeError, ValueError):
                continue
        choices = list(choices.values())
        # Cross-check even a single exact GeoNames name: a village named Tràng An
        # in another province is not sufficient evidence for the tourist site.
        crosscheck_failed = False
        if not selected_id or not choices or selected_id.startswith("photon:"):
            try:
                choices.extend(await self.resolve_photon(destination))
            except (AgentError, TimeoutError):
                crosscheck_failed = True
                if geo_failed:
                    raise AgentError("Both locality providers unavailable") from None
        if selected_id:
            selected = [p for p in choices if p.id == selected_id]
            if len(selected) != 1:
                raise LocalityChoiceRequired(
                    choices, "Địa danh đã chọn không thuộc kết quả hiện tại; vui lòng chọn lại."
                )
            return selected[0]
        exact = [p for p in choices if normalized(p.name).replace(" ", "") == key]
        if len(choices) == len(exact) == 1 and not has_administrative_match and not crosscheck_failed:
            return choices[0]
        raise LocalityChoiceRequired(
            choices,
            "Cần chọn địa danh cụ thể (đúng khu vực và loại địa điểm) để tránh lấy nhầm nơi."
            if choices
            else "Chưa xác định được địa danh. Thử tên đầy đủ kèm tỉnh/thành hoặc địa danh lân cận.",
        )

    async def resolve_photon(self, destination):
        payload, stamp, _, _ = await self.client.get(
            self.photon_url + "/api/",
            [
                ("q", destination),
                ("countrycode", "VN"),
                ("limit", "20"),
                ("include", ",".join("osm." + tag.replace(":", ".") for tag in sorted(DESTINATION_TAGS))),
            ],
            ttl=600,
        )
        if (
            payload.get("type") != "FeatureCollection"
            or not isinstance(payload.get("features"), list)
            or len(payload["features"]) > 100
        ):
            raise AgentError("Invalid fallback locality results")
        choices = {}
        for feature in payload["features"]:
            try:
                props, geometry = feature["properties"], feature["geometry"]
                if (
                    props.get("countrycode", "").upper() != "VN"
                    or geometry["type"] != "Point"
                    or f"{props.get('osm_key')}:{props.get('osm_value')}" not in DESTINATION_TAGS
                ):
                    continue
                if not isinstance(props.get("name"), str) or not relevant_name(destination, props["name"]):
                    continue
                qualifiers = [normalized(v.strip()) for v in destination.split(",")[1:] if v.strip()]
                area = normalized(
                    " ".join(str(props.get(k, "")) for k in ["state", "city", "district", "county"])
                )
                if any(q not in area for q in qualifiers):
                    continue
                kind = {"N": "node", "W": "way", "R": "relation"}[props["osm_type"]]
                identity = props["osm_id"]
                if type(identity) is not int or identity <= 0:
                    continue
                lon, lat = geometry["coordinates"]
                if isinstance(lat, bool) or isinstance(lon, bool):
                    continue
                place = Locality(
                    id=f"photon:{kind}/{identity}",
                    name=props["name"],
                    latitude=lat,
                    longitude=lon,
                    admin1=props.get("state", ""),
                    admin2=props.get("city", "") or props.get("district", ""),
                    feature_code="OSM:" + props["osm_value"],
                    source_url=f"https://www.openstreetmap.org/{kind}/{identity}",
                    fetched_at=stamp,
                    coordinate_kind="point" if kind == "node" else "geometry_center",
                )
                choices[place.id] = place
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return list(choices.values())

    async def discover(self, location, category, radius_m, keyword=""):
        if location.scope != "nearby":
            return await self.discover_region(location, category, keyword)
        params = [("lat", str(location.latitude)), ("lon", str(location.longitude)), ("limit", "50")]
        params += [("osm_tag", tag) for tag in sorted(TAGS[category])]
        if keyword:
            dy = radius_m / 111_320
            dx = dy / max(0.1, math.cos(math.radians(location.latitude)))
            params += [
                ("q", keyword),
                ("countrycode", "VN"),
                (
                    "bbox",
                    f"{location.longitude - dx},{location.latitude - dy},{location.longitude + dx},{location.latitude + dy}",
                ),
            ]
            endpoint = self.photon_url + "/api/"
        else:
            params += [("radius", str(radius_m / 1000))]
            endpoint = self.photon_url + "/reverse"
        payload, stamp, cache, retrieval = await self.client.get(endpoint, params)
        if (
            payload.get("type") != "FeatureCollection"
            or not isinstance(payload.get("features"), list)
            or len(payload["features"]) > 100
        ):
            raise AgentError("Invalid POI collection")
        results, metadata, seen = [], {}, set()
        skipped = 0
        for feature in payload["features"]:
            try:
                place, info = self.parse_feature(
                    feature, category, location, radius_m, stamp, cache, retrieval
                )
                if place is None:
                    continue
                fingerprint = (
                    normalized(place.name),
                    normalized(place.address),
                    round(place.latitude, 4),
                    round(place.longitude, 4),
                )
                if place.id in seen or fingerprint in seen:
                    continue
                seen.add(place.id)
                seen.add(fingerprint)
                results.append(place)
                metadata[place.id] = info
            except (KeyError, TypeError, ValueError):
                skipped += 1
        results.sort(key=lambda p: (metadata[p.id].distance_m, normalized(p.name), p.id))
        return results, metadata, skipped

    async def discover_region(self, location, category, keyword):
        # Bounded spatial sampling, not exhaustive pagination over the provider index.
        x0, y0, x1, y1 = location.bbox
        cols, rows = (1, 1) if keyword else (2, 3) if location.scope == "country" else (2, 2)
        results, metadata, seen = [], {}, set()
        failed = skipped = 0
        for row in range(rows):
            for col in range(cols):
                box = [
                    x0 + (x1 - x0) * col / cols,
                    y0 + (y1 - y0) * row / rows,
                    x0 + (x1 - x0) * (col + 1) / cols,
                    y0 + (y1 - y0) * (row + 1) / rows,
                ]
                params = [("countrycode", "VN"), ("limit", "50"), ("bbox", ",".join(map(str, box)))]
                # Comma-separated categories are OR. Repeating include would mean AND
                # and incorrectly require one POI to be hotel AND hostel AND campsite.
                params.append(
                    ("include", ",".join("osm." + tag.replace(":", ".") for tag in sorted(TAGS[category])))
                )
                if keyword:
                    params.append(("q", keyword))
                try:
                    payload, stamp, cache, retrieval = await self.client.get(
                        self.photon_url + "/api/", params
                    )
                    if (
                        payload.get("type") != "FeatureCollection"
                        or not isinstance(payload.get("features"), list)
                        or len(payload["features"]) > 100
                    ):
                        raise AgentError("Invalid regional POI collection")
                except (AgentError, TimeoutError):
                    failed += 1
                    continue
                for feature in payload["features"]:
                    try:
                        place, info = self.parse_feature(
                            feature, category, location, None, stamp, cache, retrieval
                        )
                        if place is None:
                            continue
                        fingerprint = (
                            normalized(place.name),
                            normalized(place.address),
                            round(place.latitude, 4),
                            round(place.longitude, 4),
                        )
                        if place.id in seen or fingerprint in seen:
                            continue
                        seen.update([place.id, fingerprint])
                        results.append(place)
                        metadata[place.id] = info
                    except (KeyError, TypeError, ValueError):
                        skipped += 1
        if failed and not results:
            raise AgentError("Regional lookup incomplete; cannot infer absence")
        for info in metadata.values():
            info.coverage_partial = failed > 0
        results.sort(key=lambda p: (metadata[p.id].distance_m, normalized(p.name), p.id))
        if location.scope == "country":
            # Round-robin the geographic query cells rather than displaying only
            # the places closest to an arbitrary national bounding-box centre.
            buckets = {}
            for place in results:
                buckets.setdefault(metadata[place.id].retrieval_url, []).append(place)
            groups = list(buckets.values())
            results = [
                group[i]
                for i in range(max((len(g) for g in groups), default=0))
                for group in groups
                if i < len(group)
            ]
        return results, metadata, skipped

    def parse_feature(self, feature, category, location, radius_m, stamp, cache, retrieval):
        if not isinstance(feature, dict):
            raise ValueError("Feature must be an object")
        props, geometry = feature["properties"], feature["geometry"]
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise ValueError("Feature geometry/properties must be objects")
        country = props.get("countrycode", "")
        if not isinstance(country, str) or country.upper() != "VN" or geometry["type"] != "Point":
            return None, None
        key, value = props.get("osm_key"), props.get("osm_value")
        if f"{key}:{value}" not in TAGS[category]:
            return None, None
        name = props.get("name")
        if not isinstance(name, str) or not name.strip():
            return None, None
        lon, lat = geometry["coordinates"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in [lon, lat]):
            raise ValueError("Coordinates must be numbers")
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Coordinates out of range")
        distance = distance_m((location.latitude, location.longitude), (lat, lon))
        if location.scope == "nearby" and distance > radius_m:
            return None, None
        if location.scope != "nearby" and not load_catalog().contains(location.id, lon, lat):
            return None, None
        kind = {"N": "node", "W": "way", "R": "relation"}.get(props["osm_type"])
        identity = props["osm_id"]
        if kind is None or type(identity) is not int or identity <= 0:
            raise ValueError("Invalid OSM identity")
        url = f"https://www.openstreetmap.org/{kind}/{identity}"
        parts = [props.get(k) for k in ["housenumber", "street", "district", "city", "state", "country"]]
        address = ", ".join(dict.fromkeys(p.strip() for p in parts if isinstance(p, str) and p.strip()))
        extra = props.get("extra") or {}
        if not isinstance(extra, dict):
            extra = {}
        try:
            website = safe_web_url(extra.get("website") or extra.get("contact:website"))
        except ValueError:
            website = None
        opening = extra.get("opening_hours")
        if not isinstance(opening, str):
            opening = None
        phone = extra.get("phone") or extra.get("contact:phone")
        if not isinstance(phone, str):
            phone = None
        place = Place(
            id=f"osm:{kind}/{identity}",
            name=name,
            address=address,
            latitude=lat,
            longitude=lon,
            source="osm_photon",
            source_url=url,
            attribution=ATTRIBUTION,
            fetched_at=stamp,
            types=[LANDMARK_TYPES.get(value, value) if category == "landmark" else value],
            coordinate_kind="point" if kind == "node" else "geometry_center",
            website_url=website,
            opening_hours_raw=opening,
            field_sources={field: url for field in ["name", "latitude", "longitude", "types"]}
            | ({"address": url} if address else {})
            | ({"website_url": url} if website else {})
            | ({"opening_hours_raw": url} if opening else {}),
        )
        return place, PlaceMetadata(
            distance_m=distance,
            address_precision="street" if props.get("street") else "locality_only" if address else "missing",
            retrieval_url=retrieval,
            cache_hit=cache,
            phone=phone,
            spatial_filter="reference_polygon" if location.scope != "nearby" else "radius",
        )
