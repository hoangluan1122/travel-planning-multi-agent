"""Place photos without exposing API keys.

WikipediaImages adds free Wikipedia/Wikimedia thumbnails to well-known sights.
GooglePhotoProxy serves Google Places photos through the backend: the browser only ever
sees a same-origin path, and only photo names this process handed out can be fetched, so
the endpoint cannot be used to spend the key on arbitrary requests.
"""

import asyncio
import re
import time
import unicodedata
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx

from .models import PlacePhoto

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


class WikipediaImages:
    def __init__(self, transport=None, lang="vi", limit=24, concurrency=3, timeout=8):
        self.transport, self.lang, self.limit = transport, lang, limit
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.cache = {}

    async def lookup(self, client, name):
        if name in self.cache:
            return self.cache[name]
        async with self.semaphore:
            response = await client.get(
                f"https://{self.lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query", "format": "json", "formatversion": "2", "generator": "search",
                    "gsrsearch": name, "gsrlimit": "1", "gsrnamespace": "0",
                    "prop": "pageimages|info", "piprop": "thumbnail", "pithumbsize": "800", "inprop": "url",
                },
            )
            response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
        photo = None
        if pages:
            page = pages[0]
            thumb = (page.get("thumbnail") or {}).get("source", "")
            if is_wikimedia_image(thumb) and titles_match(name, page.get("title", "")):
                photo = PlacePhoto(
                    url=thumb,
                    attribution=f"Ảnh: Wikipedia — {page['title']} (giấy phép xem tại trang ảnh)",
                    source_url=page.get("fullurl"),
                )
        self.cache[name] = photo
        return photo

    async def enrich(self, places):
        """Return places with a Wikipedia photo added where one clearly matches; never fails."""
        wanted = [p for p in places if p.photo is None and PHOTO_KINDS & set(p.types)][: self.limit]
        if not wanted:
            return places
        found = {}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport, headers={"User-Agent": USER_AGENT}
            ) as client:
                results = await asyncio.gather(*(self.lookup(client, p.name) for p in wanted), return_exceptions=True)
        except httpx.HTTPError:
            return places
        for place, result in zip(wanted, results, strict=True):
            if isinstance(result, PlacePhoto):
                found[place.id] = result
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
