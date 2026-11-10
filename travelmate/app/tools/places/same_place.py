"""Spot one real place listed twice under different ids.

OpenStreetMap often maps the same shop twice (a node and a building, or an old and a new
entry), and separate searches can return both: "Quán Cẩm" and "Quán Cẩm - Bún Bò Huế"
two doors apart. Two places are the same when one name, word by word, begins the other
(at least two words, so "Chùa" alone never matches) and they lie within NEAR_METERS.
"""

import math
import re

from app.tools.places.place_media import plain

NEAR_METERS = 400


def words(name):
    return re.sub(r"[^0-9a-z]+", " ", plain(name)).split()


def meters(a, b):
    lat = math.radians((a.latitude + b.latitude) / 2)
    dx = math.radians(b.longitude - a.longitude) * math.cos(lat)
    dy = math.radians(b.latitude - a.latitude)
    return 6_371_000 * math.hypot(dx, dy)


def same_place(a, b):
    short, long = sorted((words(a.name), words(b.name)), key=len)
    return len(short) >= 2 and long[:len(short)] == short and meters(a, b) <= NEAR_METERS


def richness(place):
    return sum(bool(x) for x in (place.ticket, place.photo, place.opening_hours_raw, place.website_url,
                                 place.rating))


def drop_near_duplicates(places):
    """Keep one entry per real place, at the position of its first listing.

    The kept entry is the one with more details (ticket, photo, hours, website, rating);
    on a tie, the first listed.
    """
    kept = []
    for place in places:
        twin = next((i for i, k in enumerate(kept) if same_place(k, place)), None)
        if twin is None:
            kept.append(place)
        elif richness(place) > richness(kept[twin]):
            kept[twin] = place
    return kept
