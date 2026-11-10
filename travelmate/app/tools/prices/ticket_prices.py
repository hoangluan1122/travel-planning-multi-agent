"""Attach cited entrance fees to well-known sights.

The table (app/data/ticket_prices.json) is transcribed by hand from press/official pages
with their URLs and a check date. A place gets a ticket only when its name contains one of
an entry's names, the trip is in that entry's city, and the place is a sight rather than a
restaurant, cafe or hotel. Anything not in the table stays unpriced.
"""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.core.models import TicketInfo
from app.tools.places.place_media import plain

TABLE = Path(__file__).resolve().parents[2] / "data" / "ticket_prices.json"
NOT_SIGHTS = {"restaurant", "cafe", "fast_food", "food_court", "food", "bar", "hotel", "lodging", "hostel",
              "guest_house", "motel", "resort", "camp_site"}


@lru_cache(maxsize=1)
def load_tickets():
    raw = json.loads(TABLE.read_text("utf-8"))
    checked = date.fromisoformat(raw["checked"])
    entries = []
    for item in raw["tickets"]:
        ticket = TicketInfo(
            group_id=item["id"],
            label=item["label"],
            adult_vnd=Decimal(item["adult_vnd"]) if "adult_vnd" in item else None,
            low_vnd=Decimal(item["low_vnd"]) if "low_vnd" in item else None,
            high_vnd=Decimal(item["high_vnd"]) if "high_vnd" in item else None,
            note=item.get("child_note"),
            sources=item["sources"],
            checked=checked,
        )
        entries.append(({plain(c) for c in item["cities"]}, [plain(n) for n in item["names"]], ticket))
    return entries


@lru_cache(maxsize=1)
def table_order():
    """Position of each ticket group in the table, which lists each city's best-known sight first."""
    return {ticket.group_id: i for i, (_, _, ticket) in enumerate(load_tickets())}


def fame_rank(group_id):
    """Lower is better known; groups missing from the table (should not happen) rank last."""
    order = table_order()
    return order.get(group_id, len(order))


def ticket_for(place, destination):
    if NOT_SIGHTS & set(place.types):
        return None
    name, where = plain(place.name), plain(f"{destination} {place.address}")
    for cities, names, ticket in load_tickets():
        if any(city in where for city in cities) and any(alias in name for alias in names):
            return ticket
    return None


def apply_tickets(places, destination):
    out = []
    for place in places:
        ticket = None if place.ticket else ticket_for(place, destination)
        out.append(place.model_copy(update={"ticket": ticket}) if ticket else place)
    return out
