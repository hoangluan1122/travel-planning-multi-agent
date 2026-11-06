"""Reference lodging/food/transport costs by travel style, from app/data/cost_reference.json.

The table is transcribed by hand from cited travel guides (see each entry's sources). These are
planning estimates, never quotes. Popular destinations have their own figures; any part a city
lacks, and any destination not in the table, uses the national figures, marked `national` so the
answer can say it is a country-wide level rather than a price for that city.
"""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.tools.places.place_media import plain

TABLE = Path(__file__).resolve().parents[2] / "data" / "cost_reference.json"
STYLES = {"budget": "Tiết kiệm", "mid": "Vừa phải", "high": "Cao cấp"}
CHEAPER = {"high": "mid", "mid": "budget"}
PARTS = ("lodging", "food", "transport")
PEOPLE_PER_ROOM = 2


def parse(item, national):
    return {**item, "low": Decimal(item["low"]), "high": Decimal(item["high"]), "national": national}


@lru_cache(maxsize=1)
def load_reference():
    raw = json.loads(TABLE.read_text("utf-8"))
    checked = date.fromisoformat(raw["checked"])
    national = {style: {part: parse(item, True) for part, item in parts.items()}
                for style, parts in raw["national"]["styles"].items()}
    cities = []
    for city in raw["cities"]:
        styles = {}
        for style in STYLES:
            own = city["styles"].get(style, {})
            styles[style] = {part: parse(own[part], False) if part in own else national[style][part]
                             for part in PARTS}
        cities.append({"id": city["id"], "label": city["label"], "names": [plain(n) for n in city["cities"]],
                       "styles": styles})
    country = {"id": "vietnam", "label": raw["national"]["label"], "names": [], "styles": national}
    return checked, cities, country


def reference_for(destination):
    """(checked date, entry): the destination's city entry, or the national one for anywhere else."""
    checked, cities, country = load_reference()
    where = plain(destination or "")
    for city in cities:
        if any(name in where for name in city["names"]):
            return checked, city
    return checked, country
