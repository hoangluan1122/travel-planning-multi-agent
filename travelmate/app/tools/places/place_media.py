"""Place photos without exposing API keys.

WikipediaImages adds free Wikipedia/Wikimedia thumbnails to well-known sights.
GooglePhotoProxy serves Google Places photos through the backend: the browser only ever
sees a same-origin path, and only photo names this process handed out can be fetched, so
the endpoint cannot be used to spend the key on arbitrary requests.
"""

import asyncio
import math
import re
import time
import unicodedata
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx

from app.core.models import PlacePhoto

USER_AGENT = "TravelMate-demo/0.1 (local development; https://github.com/hoangluan1122/travel-planning-multi-agent)"
PHOTO_KINDS = {"museum", "castle", "attraction", "gallery", "viewpoint", "monument", "memorial", "tomb",
               "temple", "archaeological_site", "zoo", "theme_park", "beach", "peak", "park"}
GOOGLE_PHOTO_NAME = re.compile(r"^places/[A-Za-z0-9_-]{1,300}/photos/[A-Za-z0-9_-]{1,600}$")


def plain(text):
    """Casefold and strip Vietnamese diacritics so "Lăng Tự Đức" matches "lang tu duc"."""
    text = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())


def is_wikimedia_image(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").endswith(".wikimedia.org")


def titles_match(place_name, title):
    a, b = plain(place_name), plain(title)
    return bool(a and b) and (a in b or b in a)


GENERIC_TOKENS = {"hue", "hoi", "lat", "nang", "viet", "nam", "vietnam", "city", "thanh", "pho", "quan",
                  "nha", "hang", "cafe", "coffee", "restaurant", "hotel", "khach", "san", "the", "and"}
EARTH_KM = 6371.0


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def name_tokens(name):
    return {t for t in re.split(r"[^a-z0-9]+", plain(name)) if len(t) >= 4 and t not in GENERIC_TOKENS}


def strip_html(text):
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


FOOD_TYPES = {"restaurant", "cafe", "fast_food", "food_court", "bar", "pub", "ice_cream", "bakery"}
STAY_TYPES = {"hotel", "hostel", "guest_house", "motel", "apartment", "resort", "camp_site", "lodging"}
# Food places almost never have a photo of their own in free sources. A photo of the dish in
# their name ("Bún bò Huế Kim Đồng"), labelled as an illustration, is honest and better than
# none. (keywords, Vietnamese Wikipedia title, label, keywords also match without accents).
# Without accents some words collide ("pho" is also "phố", "lau" is "lâu"), so those match
# only with their accents.
DISHES = [
    (("bún bò",), "Bún bò Huế", "bún bò Huế", True),
    (("phở",), "Phở", "phở", False),
    (("cơm tấm",), "Cơm tấm", "cơm tấm", True),
    (("bánh mì", "banh my"), "Bánh mì Việt Nam", "bánh mì", True),
    (("cao lầu",), "Cao lầu", "cao lầu", True),
    (("mì quảng",), "Mì Quảng", "mì Quảng", True),
    (("bánh xèo",), "Bánh xèo", "bánh xèo", True),
    (("bún chả",), "Bún chả", "bún chả", True),
    (("bún riêu",), "Bún riêu cua", "bún riêu", True),
    (("bánh canh",), "Bánh canh", "bánh canh", True),
    (("bánh căn",), "Bánh căn", "bánh căn", True),
    (("bánh khọt",), "Bánh khọt", "bánh khọt", True),
    (("bánh bèo",), "Bánh bèo", "bánh bèo", True),
    (("bánh cuốn",), "Bánh cuốn", "bánh cuốn", True),
    (("cơm hến",), "Cơm hến", "cơm hến", True),
    (("cơm gà",), "Cơm gà", "cơm gà", True),
    (("hủ tiếu", "hu tiu"), "Hủ tiếu", "hủ tiếu", True),
    (("nem nướng",), "Nem nướng", "nem nướng", True),
    (("gỏi cuốn",), "Gỏi cuốn", "gỏi cuốn", True),
    (("cơm chiên", "fried rice"), "Cơm chiên", "cơm chiên", True),
    (("lẩu", "hotpot", "hot pot"), "Lẩu", "lẩu", False),
    (("hải sản", "seafood"), "Hải sản", "hải sản", True),
    (("ốc",), "Ốc", "ốc", False),
    (("nướng", "bbq", "barbecue", "grill"), "Nướng", "đồ nướng", True),
    (("chay", "vegetarian", "vegan"), "Ẩm thực chay", "món chay", True),
    (("pizza", "pizzeria"), "Pizza", "pizza", True),
    (("burger",), "Hamburger", "hamburger", True),
    (("pasta", "spaghetti", "italian", "trattoria"), "Ẩm thực Ý", "món Ý", True),
    (("sushi", "japanese", "ramen"), "Ẩm thực Nhật Bản", "món Nhật", True),
    (("korean", "hàn quốc"), "Ẩm thực Triều Tiên", "món Hàn", True),
    (("indian", "ấn độ", "curry"), "Ẩm thực Ấn Độ", "món Ấn", True),
    (("steak", "bít tết", "beefsteak"), "Bít tết", "bít tết", True),
    (("gà rán", "fried chicken"), "Gà rán", "gà rán", True),
    (("trà sữa", "milk tea", "bubble tea"), "Trà sữa", "trà sữa", True),
]


def folded(text):
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def has_word(text, word):
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def dish_for(place):
    """(Wikipedia title, label) of what a food place serves, judged from its name and type; else None."""
    types = set(place.types or [])
    if not types & FOOD_TYPES:
        return None
    name, flat = folded(place.name), plain(place.name)
    for words, title, label, accents_optional in DISHES:
        for word in words:
            if has_word(name, word) or (accents_optional and has_word(flat, plain(word))):
                return title, label
    if "cafe" in types or has_word(flat, "cafe") or has_word(flat, "coffee") or has_word(name, "cà phê"):
        return "Quán cà phê", "quán cà phê"
    return "Ẩm thực Việt Nam", "ẩm thực Việt Nam"


def ascii_name(name):
    return all(ord(ch) < 128 for ch in name)


class WikipediaImages:
    """Free photos for places, tried in order of confidence; never fails a search.

    1. Wikipedia article whose title matches the place name (sights only).
    2. Wikidata item with a matching label and coordinates within 1.5 km, using its image.
    3. Wikimedia Commons file taken within 150 m whose title shares a distinctive word
       with the place name.
    Commons photos carry the author and licence from the file's metadata.
    """

    def __init__(self, transport=None, lang="vi", limit=40, concurrency=6, timeout=6, deadline_s=12):
        self.transport, self.lang, self.limit = transport, lang, limit
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout, self.deadline_s = timeout, deadline_s
        self.cache = {}
        self.illustrations = {}  # Wikipedia title -> PlacePhoto (or None: the article has no photo)
        self.illustration_locks = {}

    async def get(self, client, url, params):
        async with self.semaphore:
            response = await client.get(url, params={"format": "json", "formatversion": "2", **params})
            response.raise_for_status()
            return response.json()

    async def wikipedia(self, client, place, lang=None):
        data = await self.get(client, f"https://{lang or self.lang}.wikipedia.org/w/api.php", {
            "action": "query", "generator": "search", "gsrsearch": place.name, "gsrlimit": "1",
            "gsrnamespace": "0", "prop": "pageimages|info", "piprop": "thumbnail", "pithumbsize": "800",
            "inprop": "url",
        })
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return None
        page = pages[0]
        thumb = (page.get("thumbnail") or {}).get("source", "")
        if not (is_wikimedia_image(thumb) and titles_match(place.name, page.get("title", ""))):
            return None
        return PlacePhoto(
            url=thumb,
            attribution=f"Ảnh: Wikipedia — {page['title']} (giấy phép xem tại trang ảnh)",
            source_url=page.get("fullurl"),
        )

    async def commons_file(self, client, title):
        data = await self.get(client, "https://commons.wikimedia.org/w/api.php", {
            "action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata",
            "iiurlwidth": "800",
        })
        pages = data.get("query", {}).get("pages", [])
        info = ((pages[0].get("imageinfo") or [None])[0]) if pages else None
        if not info or not is_wikimedia_image(info.get("thumburl", "")):
            return None
        meta = info.get("extmetadata") or {}
        author = strip_html((meta.get("Artist") or {}).get("value", ""))[:120] or "tác giả trên Commons"
        licence = strip_html((meta.get("LicenseShortName") or {}).get("value", ""))[:60] or "xem trang ảnh"
        return PlacePhoto(
            url=info["thumburl"],
            attribution=f"Ảnh: {author} — {licence}, Wikimedia Commons",
            source_url=info.get("descriptionurl"),
        )

    async def wikidata(self, client, place):
        found = await self.get(client, "https://www.wikidata.org/w/api.php", {
            "action": "wbsearchentities", "search": place.name, "language": self.lang, "uselang": self.lang,
            "type": "item", "limit": "3",
        })
        ids = [item["id"] for item in found.get("search", []) if titles_match(place.name, item.get("label", ""))]
        if not ids:
            return None
        entities = await self.get(client, "https://www.wikidata.org/w/api.php", {
            "action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
        })
        for ident in ids:
            claims = (entities.get("entities", {}).get(ident) or {}).get("claims", {})
            try:
                coord = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
                image = claims["P18"][0]["mainsnak"]["datavalue"]["value"]
            except (KeyError, IndexError, TypeError):
                continue
            if distance_km(place.latitude, place.longitude, coord["latitude"], coord["longitude"]) <= 1.5:
                return await self.commons_file(client, f"File:{image}")
        return None

    async def commons_nearby(self, client, place):
        tokens = name_tokens(place.name)
        if not tokens:
            return None
        data = await self.get(client, "https://commons.wikimedia.org/w/api.php", {
            "action": "query", "list": "geosearch", "gscoord": f"{place.latitude}|{place.longitude}",
            "gsradius": "150", "gsnamespace": "6", "gslimit": "10",
        })
        for hit in data.get("query", {}).get("geosearch", []):
            if tokens & name_tokens(hit.get("title", "")):
                return await self.commons_file(client, hit["title"])
        return None

    async def wikipedia_en(self, client, place):
        """English Wikipedia, for sights OpenStreetMap names in English ("Hoi An Museum of ...")."""
        return await self.wikipedia(client, place, "en") if ascii_name(place.name) else None

    async def illustration(self, client, title, label):
        """The lead photo of a Wikipedia article about a dish, fetched once per title.

        A failed lookup is not remembered, so the next search tries again.
        """
        async with self.illustration_locks.setdefault(title, asyncio.Lock()):
            if title in self.illustrations:
                return self.illustrations[title]
            try:
                data = await self.get(client, f"https://{self.lang}.wikipedia.org/w/api.php", {
                    "action": "query", "titles": title, "redirects": "1", "prop": "pageimages|info",
                    "piprop": "thumbnail", "pithumbsize": "800", "inprop": "url",
                })
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return None
            pages = data.get("query", {}).get("pages", [])
            thumb = ((pages[0].get("thumbnail") or {}).get("source", "")) if pages else ""
            photo = PlacePhoto(
                url=thumb, attribution=f"Ảnh minh hoạ {label} — Wikipedia, không phải ảnh của quán",
                source_url=pages[0].get("fullurl"), illustration=True,
            ) if is_wikimedia_image(thumb) else None
            self.illustrations[title] = photo
            return photo

    async def find(self, client, place):
        if place.id in self.cache:
            return self.cache[place.id]
        types = set(place.types or [])
        if types & (FOOD_TYPES | STAY_TYPES):
            sources = [self.wikidata, self.commons_nearby]
        else:
            sights = PHOTO_KINDS & types
            sources = ([self.wikipedia, self.wikipedia_en] if sights else []) + [self.wikidata, self.commons_nearby]
        photo = None
        for source in sources:
            try:
                photo = await source(client, place)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                photo = None
            if photo:
                break
        if photo is None and (dish := dish_for(place)):
            photo = await self.illustration(client, *dish)
        self.cache[place.id] = photo
        return photo

    async def enrich(self, places):
        """Return places with a free photo added where one clearly matches, within a time budget."""
        wanted = [p for p in places if p.photo is None][: self.limit]
        if not wanted:
            return places
        found = {}
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, headers={"User-Agent": USER_AGENT}
        ) as client:
            tasks = {asyncio.create_task(self.find(client, p)): p for p in wanted}
            done, pending = await asyncio.wait(tasks, timeout=self.deadline_s)
            for task in pending:
                task.cancel()
            for task in done:
                if not task.cancelled() and task.exception() is None and task.result():
                    found[tasks[task].id] = task.result()
        return [p.model_copy(update={"photo": found[p.id]}) if p.id in found else p for p in places]


class GooglePhotoProxy:
    """Remembers photo names returned by Places searches and resolves them to image URLs."""

    def __init__(self, maps_key, transport=None, max_names=2000, ttl_s=3000):
        self.maps_key, self.transport = maps_key, transport
        self.allowed = OrderedDict()
        self.resolved = {}
        self.max_names, self.ttl_s = max_names, ttl_s

    def register(self, name):
        if not GOOGLE_PHOTO_NAME.fullmatch(name):
            return None
        self.allowed[name] = True
        self.allowed.move_to_end(name)
        while len(self.allowed) > self.max_names:
            self.allowed.popitem(last=False)
        return "/api/v1/places/photo?ref=" + name

    async def resolve(self, name):
        """Short-lived keyless googleusercontent URL for an issued photo name, else None."""
        if name not in self.allowed:
            return None
        cached = self.resolved.get(name)
        if cached and time.monotonic() - cached[0] < self.ttl_s:
            return cached[1]
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            response = await client.get(
                f"https://places.googleapis.com/v1/{name}/media",
                params={"maxWidthPx": "800", "skipHttpRedirect": "true"},
                headers={"X-Goog-Api-Key": self.maps_key},
            )
            response.raise_for_status()
        uri = response.json().get("photoUri", "")
        if not uri.startswith("https://"):
            return None
        self.resolved[name] = (time.monotonic(), uri)
        return uri
