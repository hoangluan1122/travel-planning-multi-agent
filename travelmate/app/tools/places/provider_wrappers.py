"""Wrappers around a place provider: a one-day cache, and hiding places an admin removed.

Both forward everything else to the provider they wrap, so agents use them like the
provider itself: `HidingProvider(CachingProvider(OpenDataProvider(), store, "open_data"), ...)`.
"""

import asyncio
import logging
import unicodedata

from app.core.models import PlaceResult

logger = logging.getLogger(__name__)

PLACE_CACHE_TTL_S = 24 * 3600
# Bump when what a place search returns changes (e.g. photos), so cached results are not reused.
PLACE_CACHE_VERSION = 2


class CachingProvider:
    """Keeps a complete place search per destination for a day, in the product database.

    The map lookups take ~15 s of every plan; a second plan for the same city reuses them.
    A result where a source failed and a fallback filled in is not kept, so an outage does
    not leave a thin list for a day. The database is the cache so it survives the free
    server going to sleep.
    """

    def __init__(self, provider, store, name, ttl_s=PLACE_CACHE_TTL_S):
        self.inner, self.store, self.name, self.ttl_s = provider, store, name, ttl_s

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def key(self, trip):
        # "Đà Nẵng", "đà nẵng" and " Đà  Nẵng " share one entry.
        destination = " ".join(unicodedata.normalize("NFC", trip.destination).casefold().split())
        return f"{self.name}:v{PLACE_CACHE_VERSION}:{destination}"

    async def search(self, trip):
        key = self.key(trip)
        try:
            cached = await asyncio.to_thread(self.store.cached_places, key, self.ttl_s)
            if cached is not None:
                return PlaceResult.model_validate(cached)
        except Exception as exc:  # a broken cache must never break planning
            logger.warning("place_cache read outcome=failed error_type=%s", type(exc).__name__)
        # Providers that can tell a complete result from a fallback say so; others are trusted.
        if hasattr(self.inner, "search_cacheable"):
            result, complete = await self.inner.search_cacheable(trip)
        else:
            result, complete = await self.inner.search(trip), True
        if complete:
            try:
                await asyncio.to_thread(self.store.cache_places, key, result.model_dump(mode="json"))
            except Exception as exc:
                logger.warning("place_cache write outcome=failed error_type=%s", type(exc).__name__)
        return result


class HidingProvider:
    """Wraps a place provider so places an admin hid never reach searches, plans or the chat."""

    def __init__(self, provider, hidden_ids):
        self.inner, self.hidden_ids = provider, hidden_ids

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def filtered(self, result):
        hidden = await asyncio.to_thread(self.hidden_ids)
        if not hidden:
            return result
        update = {"places": [p for p in result.places if p.id not in hidden]}
        if getattr(result, "stays", None):
            update["stays"] = [p for p in result.stays if p.id not in hidden]
        return result.model_copy(update=update)

    async def search(self, trip):
        return await self.filtered(await self.inner.search(trip))

    async def search_places(self, query):
        return await self.filtered(await self.inner.search_places(query))
