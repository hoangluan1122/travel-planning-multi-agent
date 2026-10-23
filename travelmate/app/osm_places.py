"""Bounded Vietnam locality/POI lookup from OSM, not a complete places directory.

The public Overpass default is for modest local research only. Configure a managed
or self-hosted endpoint for a deployed application. No public Nominatim dependency.
"""

import asyncio
import json
import math
import re
import time
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from .agents import AgentError, BaseAgent
from .models import Place, PlaceResult, PlaceSearchRequest
from .place_locations import (
    LocationCandidate,
    LocationChoiceRequired,
    LocationQuery,
    LocationResult,
    PlaceDiscoveryResult,
)

ATTRIBUTION = "© OpenStreetMap contributors — ODbL, https://www.openstreetmap.org/copyright"
PREFIX = '[out:json][timeout:15][maxsize:16777216];area["ISO3166-1"="VN"]["admin_level"="2"]->.vn;'
CATEGORIES = {
    "hotel": '["tourism"~"^(hotel|hostel|guest_house|motel|resort)$"]',
    "restaurant": '["amenity"~"^(restaurant|food_court)$"]',
    "attraction": '["tourism"~"^(attraction|museum|viewpoint|zoo|theme_park|gallery)$"]',
}


def normalized(value):
    # GeoNames also uses Latin eth (Ð/ð) for Vietnamese Đ in some names.
    value = unicodedata.normalize("NFD", value.casefold().replace("đ", "d").replace("ð", "d"))
    return " ".join("".join(c for c in value if unicodedata.category(c) != "Mn").split())


def ql_string(value):
    return json.dumps(value, ensure_ascii=False)


def aliases(destination):
    # A tiny explicit alias table, not inferred administrative/geographic equivalence.
    key = normalized(destination).replace(" ", "")
    if key == "sapa":
        return ["Sa Pa", "Sapa"]
    if key == "danang":
        return ["Đà Nẵng", "Da Nang"]
    return [destination.strip()]


def distance_m(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(x)))


def safe_web_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    url = urlsplit(value)
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
        return None
    return value


def address_from(tags):
    parts = [
        tags.get(key)
        for key in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:province")
    ]
    return ", ".join(dict.fromkeys(p for p in parts if isinstance(p, str) and p.strip()))


class OSMPlaceProvider:
    def __init__(
        self,
        endpoint="https://overpass-api.de/api/interpreter",
        *,
        transport=None,
        cache_ttl=600,
        min_interval=1.0,
    ):
        url = urlsplit(endpoint)
        if url.scheme not in {"https", "http"} or not url.hostname:
            raise ValueError("Invalid server-configured Overpass endpoint")
        if not 0 < cache_ttl <= 3600 or min_interval < 0:
            raise ValueError("Invalid provider cache/rate settings")
        self.endpoint, self.transport = endpoint, transport
        self.cache_ttl, self.min_interval = cache_ttl, min_interval
        self._lock = asyncio.Lock()
        self._cache = {}
        self._last_request = 0.0
        self._cooldown_until = 0.0

    async def _query(self, query):
        # One in-flight query per provider instance; same-query cache coalesces callers.
        async with self._lock:
            now = time.monotonic()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if query in self._cache:
                _, payload, fetched = self._cache[query]
                return payload, fetched
            if now < self._cooldown_until:
                raise AgentError("Provider cooldown active; try later")
            delay = self.min_interval - (now - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=22,
                    headers={"User-Agent": "TravelMate-Graduation/0.1 (local research)"},
                ) as client:
                    response = await client.post(self.endpoint, data={"data": query})
                    if response.status_code in {429, 406}:
                        self._cooldown_until = time.monotonic() + 30
                    response.raise_for_status()
                if len(response.content) > 3_000_000:
                    raise ValueError("Provider response too large")
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("remark"):
                    raise ValueError("Overpass reported partial results/error")
                elements = payload["elements"]
                if not isinstance(elements, list) or len(elements) > 101:
                    raise ValueError("Invalid element collection")
            except httpx.TimeoutException:
                raise TimeoutError("OpenStreetMap query timed out") from None
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise AgentError("OpenStreetMap provider unavailable or invalid response") from None
            fetched = datetime.now(UTC)
            if len(self._cache) >= 128:
                self._cache.pop(next(iter(self._cache)))
            self._cache[query] = (time.monotonic() + self.cache_ttl, elements, fetched)
            return elements, fetched

    async def resolve_locations(self, destination):
        if not 2 <= len(destination.strip()) <= 200:
            raise ValueError("Invalid destination length")
        pattern = "^(" + "|".join(re.escape(name) for name in aliases(destination)) + ")$"
        selects = "".join(
            f'node["place"~"^(city|town|village|suburb)$"][{ql_string(tag)}~{ql_string(pattern)},i](area.vn);'
            for tag in ["name", "name:vi", "name:en"]
        )
        raw, _ = await self._query(PREFIX + "(" + selects + ");out body 11;")
        candidates = {}
        for item in raw:
            try:
                tags = item["tags"]
                if item["type"] != "node" or type(item["id"]) is not int or item["id"] <= 0:
                    raise ValueError("Bad locality identity")
                if tags.get("place") not in {"city", "town", "village", "suburb"}:
                    continue
                candidate = LocationCandidate(
                    id=f"osm:node/{item['id']}",
                    name=tags.get("name:vi") or tags["name"],
                    latitude=item["lat"],
                    longitude=item["lon"],
                    locality_type=tags["place"],
                    address=address_from(tags),
                    source_url=f"https://www.openstreetmap.org/node/{item['id']}",
                )
                candidates[candidate.id] = candidate
            except (KeyError, TypeError, ValueError):
                continue
        if raw and not candidates:
            raise AgentError("Locality records have no usable coordinates")
        return list(candidates.values())[:10]

    async def search_places(self, query):
        locations = await self.resolve_locations(query.destination)
        if query.location_id:
            matches = [p for p in locations if p.id == query.location_id]
        else:
            matches = locations if len(locations) == 1 else []
        if len(matches) != 1:
            raise LocationChoiceRequired(locations, "Chọn địa danh cụ thể; không tự chọn kết quả đầu tiên.")
        location = matches[0]
        region = f"(area.vn)(around:{query.radius_m},{location.latitude},{location.longitude})"
        raw, fetched = await self._query(
            PREFIX + f"nwr{CATEGORIES[query.category]}{region};out body center 101;"
        )
        places, seen, fingerprints = [], set(), set()
        usable = 0
        warnings = [
            ATTRIBUTION,
            "Dữ liệu cộng đồng có thể thiếu hoặc cũ; không xác nhận phòng trống, giá hoặc giờ mở cửa.",
            "Tìm trong bán kính quanh tâm địa danh đã chọn, không đại diện toàn bộ tỉnh.",
        ]
        if len(raw) >= 101:
            warnings.append(
                "Đã chạm giới hạn ứng viên; kết quả không phải danh sách đầy đủ hoặc gần nhất toàn khu vực."
            )
        for item in raw[:100]:
            try:
                place = self._place(item, fetched)
                usable += 1
                if place.id in seen:
                    continue
                seen.add(place.id)
                if (
                    distance_m((location.latitude, location.longitude), (place.latitude, place.longitude))
                    > query.radius_m
                ):
                    continue
                keyword = normalized(query.keyword.strip())
                haystack = normalized(f"{place.name} {place.address} " + " ".join(place.types))
                if keyword and keyword not in haystack:
                    continue
                fingerprint = (
                    normalized(place.name),
                    normalized(place.address),
                    round(place.latitude, 5),
                    round(place.longitude, 5),
                )
                if fingerprint in fingerprints:
                    warnings.append("Đã gộp bản ghi trùng tên/địa chỉ và gần như cùng tọa độ.")
                    continue
                fingerprints.add(fingerprint)
                places.append(place)
            except (ValueError, KeyError, TypeError):
                warnings.append("Bỏ qua bản ghi thiếu tên/tọa độ hoặc không hợp lệ.")
        if raw and not usable:
            raise AgentError("Place provider returned no valid records")
        places.sort(
            key=lambda p: (
                distance_m((location.latitude, location.longitude), (p.latitude, p.longitude)),
                p.id,
            )
        )
        if not places:
            warnings.append(
                "Không có ứng viên phù hợp trong dữ liệu nguồn; không chứng minh ngoài thực tế không có."
            )
        return PlaceResult(places=places[: query.limit], warnings=list(dict.fromkeys(warnings)))

    def _place(self, item, fetched):
        kind, identity = item["type"], item["id"]
        if kind not in {"node", "way", "relation"} or type(identity) is not int or identity <= 0:
            raise ValueError("Bad OSM identity")
        tags = item["tags"]
        if not isinstance(tags, dict):
            raise ValueError("Invalid tags")
        coordinates = item if kind == "node" else item["center"]
        source = f"https://www.openstreetmap.org/{kind}/{identity}"
        image_ref = tags.get("image") or tags.get("wikimedia_commons")
        website = safe_web_url(tags.get("website") or tags.get("contact:website"))
        fields = {"name": source, "latitude": source, "longitude": source}
        if address_from(tags):
            fields["address"] = source
        if tags.get("opening_hours"):
            fields["opening_hours_raw"] = source
        if website:
            fields["website_url"] = source
        if image_ref:
            fields["image_reference"] = source
        return Place(
            id=f"osm:{kind}/{identity}",
            name=tags.get("name:vi") or tags["name"],
            address=address_from(tags),
            latitude=coordinates["lat"],
            longitude=coordinates["lon"],
            source="openstreetmap",
            source_url=source,
            attribution=ATTRIBUTION,
            fetched_at=fetched,
            coordinate_kind="point" if kind == "node" else "geometry_center",
            opening_hours_raw=tags.get("opening_hours"),
            website_url=website,
            image_reference=image_ref,
            field_sources=fields,
            types=[str(tags[key]) for key in ["tourism", "amenity", "cuisine"] if tags.get(key)],
        )

    async def get_details(self, place_id):
        match = re.fullmatch(r"osm:(node|way|relation)/([1-9][0-9]{0,19})", place_id)
        if not match:
            raise AgentError("Invalid OSM place ID")
        kind, identity = match.groups()
        raw, fetched = await self._query(PREFIX + f"{kind}({identity})(area.vn);out body center 1;")
        if len(raw) != 1:
            raise AgentError("Place not found in the Vietnam data scope")
        try:
            result = self._place(raw[0], fetched)
            if result.id != place_id:
                raise ValueError("Identity mismatch")
            return result
        except (KeyError, TypeError, ValueError, ValidationError):
            raise AgentError("Invalid place details") from None


class OSMLocationTool(BaseAgent[LocationQuery, LocationResult]):
    name, input_schema, output_schema = "osm_locations", LocationQuery, LocationResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return LocationResult(
            candidates=await self.provider.resolve_locations(data.destination),
            warnings=[
                ATTRIBUTION,
                "Chỉ tìm city/town/village/suburb; không tự chọn tỉnh hoặc địa danh đầu tiên.",
            ],
        )


class OSMSearchTool(BaseAgent[PlaceSearchRequest, PlaceDiscoveryResult]):
    name, input_schema, output_schema = "osm_places", PlaceSearchRequest, PlaceDiscoveryResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        try:
            result = await self.provider.search_places(data)
        except LocationChoiceRequired as exc:
            return PlaceDiscoveryResult(
                status="needs_location", location_options=exc.candidates, warnings=[ATTRIBUTION, exc.reason]
            )
        return PlaceDiscoveryResult(
            status="candidates" if result.places else "no_results",
            places=result.places,
            warnings=result.warnings,
        )
