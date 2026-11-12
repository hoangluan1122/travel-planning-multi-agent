"""Sights near a locality from Vietnamese Wikipedia, for when Photon/OpenStreetMap is down.

The public Photon and Overpass servers are free and often at capacity; then a plan had no
places at all. Wikipedia's geosearch is free, keyless and fast, and its articles with
coordinates near a city centre are mostly what a visitor would see (temples, tombs,
palaces, museums, markets). Only titles that name a sight are kept: wards, districts,
rivers, schools and historical events also have coordinates.
"""

import math
import re
import unicodedata
from datetime import UTC, datetime

import httpx

from app.core.models import Place, PlacePhoto
from app.tools.places.place_media import USER_AGENT, is_wikimedia_image

ATTRIBUTION = "Wikipedia tiếng Việt — CC BY-SA 4.0"
MAX_RADIUS_M = 10_000  # the geosearch API limit
# A title that starts with one of these names a sight; the value is the place type used for
# ranking (ATTRACTION_RANK in open_data_provider.py). Matched with accents: without them
# "Phú" would read as "Phủ", "Vĩnh Long" as "Vịnh", "Đồng" as "Động".
LEADING_WORDS = {
    "bảo tàng": "museum", "hoàng thành": "castle", "kinh thành": "castle", "tử cấm thành": "castle",
    "thành cổ": "castle", "điện": "castle", "cung": "castle", "dinh": "castle", "phủ": "castle",
    "lăng": "tomb", "chùa": "temple", "đền": "temple", "đình": "temple", "miếu": "temple",
    "văn miếu": "temple", "quốc tử giám": "temple", "nhà thờ": "temple", "thánh thất": "temple",
    "hội quán": "temple", "tháp": "monument", "tượng đài": "monument", "đàn": "monument",
    "phố cổ": "attraction", "khu du lịch": "attraction", "khu di tích": "attraction", "di tích": "attraction",
    "chợ": "attraction", "cầu": "attraction", "nhà hát": "attraction", "quảng trường": "attraction",
    "thác": "attraction", "hồ": "viewpoint", "đèo": "viewpoint", "núi": "peak", "vịnh": "beach",
    "bãi biển": "beach", "bãi": "beach", "đảo": "beach", "hang": "cave_entrance", "động": "cave_entrance",
    "công viên": "park", "vườn quốc gia": "national_park", "vườn": "park",
}
# ... or ends with one of these ("Phu Văn lâu", "Kỳ đài", "Ngọ Môn", "Nghênh Lương đình").
TRAILING_WORDS = {"lâu": "castle", "đài": "monument", "môn": "castle", "đình": "temple", "miếu": "temple"}
# Places named like sights that are towns or districts.
NOT_SIGHTS = ("điện biên", "điện bàn", "hồ chí minh", "phủ lý", "cầu giấy", "chợ mới", "chợ gạo", "chợ đồn",
              "đình lập", "núi thành")
# Wikipedia short descriptions of administrative units.
ADMIN_DESCRIPTIONS = ("phường thuộc", "xã thuộc", "quận thuộc", "huyện thuộc", "thị xã", "thị trấn thuộc",
                      "quận nội thành", "thành phố tỉnh lỵ", "thành phố trực thuộc", "đơn vị hành chính")
PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")


def folded(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def sight_type(title):
    """The place type for a Wikipedia title that names a sight, else None."""
    name = folded(PAREN.sub("", title))
    if name.startswith(NOT_SIGHTS):
        return None
    words = name.split()
    for size in (3, 2, 1):
        head = " ".join(words[:size])
        if len(words) > size and head in LEADING_WORDS:
            return LEADING_WORDS[head]
    if len(words) >= 2 and words[-1] in TRAILING_WORDS:
        return TRAILING_WORDS[words[-1]]
    return None


def meters(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


class WikipediaPlaces:
    """nearby(location, radius_m) -> sights as Place records, photo first then nearest; [] on failure."""

    def __init__(self, transport=None, lang="vi", timeout=8, limit=100):
        self.transport, self.lang, self.timeout, self.limit = transport, lang, timeout, limit

    async def pages(self, location, radius_m):
        params = {
            "action": "query", "format": "json", "formatversion": "2", "generator": "geosearch",
            "ggscoord": f"{location.latitude}|{location.longitude}",
            "ggsradius": str(min(MAX_RADIUS_M, int(radius_m))), "ggslimit": str(self.limit),
            "prop": "coordinates|pageimages|description|info", "colimit": "max",
            "piprop": "thumbnail", "pithumbsize": "800", "pilimit": "50", "inprop": "url",
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                     headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(f"https://{self.lang}.wikipedia.org/w/api.php", params=params)
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            raise ValueError("Invalid geosearch payload")
        return pages

    async def nearby(self, location, radius_m):
        try:
            pages = await self.pages(location, radius_m)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return []
        stamp = datetime.now(UTC)
        found = []
        for page in pages:
            try:
                row = self.place(page, location, stamp)
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if row is not None:
                found.append(row)
        # A part of a bigger site that is also listed ("Ngọ Môn (Hoàng thành Huế)" next to
        # "Hoàng thành Huế") would fill a day with one ticketed complex.
        names = {folded(place.name) for place, _, _ in found}
        found = [row for row in found if row[2] not in names]
        found.sort(key=lambda row: (row[0].photo is None, row[1]))
        return [place for place, _, _ in found]

    def place(self, page, location, stamp):
        """(Place, metres from the centre, folded name of the site it is part of) or None."""
        title = page["title"]
        kind = sight_type(title)
        description = (page.get("description") or "").strip()
        if kind is None or any(words in folded(description) for words in ADMIN_DESCRIPTIONS):
            return None
        coord = page["coordinates"][0]
        lat, lon = float(coord["lat"]), float(coord["lon"])
        match = PAREN.search(title)
        url = page.get("fullurl") or f"https://{self.lang}.wikipedia.org/?curid={page['pageid']}"
        thumb = (page.get("thumbnail") or {}).get("source", "")
        photo = PlacePhoto(url=thumb, attribution=f"Ảnh: Wikipedia — {title} (giấy phép xem tại trang ảnh)",
                           source_url=url) if is_wikimedia_image(thumb) else None
        place = Place(
            id=f"wikipedia:{self.lang}/{page['pageid']}",
            name=PAREN.sub("", title).strip(),
            address=", ".join(part for part in [description[:200], location.name] if part),
            latitude=lat,
            longitude=lon,
            source="wikipedia",
            source_url=url,
            attribution=ATTRIBUTION,
            fetched_at=stamp,
            types=[kind],
            coordinate_kind="point",
            photo=photo,
            field_sources={field: url for field in ["name", "latitude", "longitude", "types"]},
        )
        return place, meters(location.latitude, location.longitude, lat, lon), folded(match.group(1)) if match else ""
