"""Reference lodging/food/transport costs by travel style, from app/data/cost_reference.json.

The table is transcribed by hand from cited travel guides (see each entry's sources). These are
planning estimates, never quotes: a city not in the table gets no reference costs, and the budget
agent then says so instead of guessing.
"""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from .place_media import plain

TABLE = Path(__file__).resolve().parent / "data" / "cost_reference.json"
STYLES = {"budget": "Tiết kiệm", "mid": "Vừa phải", "high": "Cao cấp"}
CHEAPER = {"high": "mid", "mid": "budget"}
PEOPLE_PER_ROOM = 2


@lru_cache(maxsize=1)
def load_reference():
    raw = json.loads(TABLE.read_text("utf-8"))
    checked = date.fromisoformat(raw["checked"])
    cities = []
    for city in raw["cities"]:
        styles = {
            style: {
                part: {**item, "low": Decimal(item["low"]), "high": Decimal(item["high"])}
                for part, item in parts.items()
            }
            for style, parts in city["styles"].items()
        }
        cities.append({"id": city["id"], "label": city["label"], "names": [plain(n) for n in city["cities"]],
                       "styles": styles})
    return checked, cities


def reference_for(destination):
    """(checked date, city entry) for a destination in the table, else (checked date, None)."""
    checked, cities = load_reference()
    where = plain(destination or "")
    for city in cities:
        if any(name in where for name in city["names"]):
            return checked, city
    return checked, None
