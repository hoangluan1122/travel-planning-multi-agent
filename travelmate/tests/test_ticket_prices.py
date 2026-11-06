"""Cited entrance fees: matched by name and city, sights only, one ticket per group."""

from decimal import Decimal

import pytest
from test_planning import payload

from app.agents.budget import BudgetAgent
from app.core.models import Activity, BudgetInput, Context, Day, Draft, Place, PlaceResult, TripRequest
from app.tools.prices.ticket_prices import apply_tickets, load_tickets


def place(ident, name, types=("attraction",), address="Huế, Việt Nam"):
    return Place(id=ident, name=name, address=address, latitude=16.47, longitude=107.58, source="t", types=list(types))


def test_every_table_entry_has_a_price_and_https_sources():
    for _, names, ticket in load_tickets():
        assert names and ticket.sources and all(u.startswith("https://") for u in ticket.sources)
        assert ticket.adult_vnd is not None or ticket.low_vnd is not None


def test_tickets_match_name_and_city_but_never_food_or_hotels():
    out = apply_tickets([
        place("a", "Hoàng Thành Huế", ["museum"]), place("b", "Lang Khai Dinh", ["tomb"]),
        place("c", "Bún bò Đại Nội", ["restaurant"]), place("d", "Khách sạn Tử Cấm Thành", ["hotel"]),
        place("e", "Công viên Thương Bạc", ["park"]),
    ], "Huế")
    tickets = {p.id: p.ticket and p.ticket.group_id for p in out}
    assert tickets == {"a": "hue-dai-noi", "b": "hue-khai-dinh", "c": None, "d": None, "e": None}
    assert apply_tickets([place("x", "Lăng Khải Định", address="Đà Lạt")], "Đà Lạt")[0].ticket is None


@pytest.mark.asyncio
async def test_budget_counts_one_ticket_per_group_and_ranges_as_estimates():
    trip = TripRequest(**payload())  # 2 travelers
    places = apply_tickets([
        place("a", "Hoàng Thành Huế", ["museum"]), place("b", "Điện Thái Hòa"), place("c", "Lăng Tự Đức", ["tomb"]),
    ], "Huế") + apply_tickets([place("h", "Hội Quán Phước Kiến", address="Hội An")], "Hội An")
    draft = Draft(days=[
        Day(date=trip.start_date, activities=[
            Activity(place_id="a", start_minute=480, end_minute=600), Activity(place_id="b", start_minute=620, end_minute=700)]),
        Day(date=trip.end_date, activities=[
            Activity(place_id="c", start_minute=480, end_minute=600), Activity(place_id="h", start_minute=620, end_minute=700)]),
    ])
    result = await BudgetAgent().run(BudgetInput(trip=trip, draft=draft, places=PlaceResult(places=places)), Context())
    assert result.known_subtotal == Decimal(2 * (200000 + 150000))  # Đại Nội once, not twice
    tickets = next(line for line in result.lines if line.category == "tickets")
    assert tickets.low_vnd == result.known_subtotal + 2 * 80000
    assert tickets.high_vnd == result.known_subtotal + 2 * 120000
    assert not any("Hoàng Thành" in u or "Điện Thái Hòa" in u for u in result.unknown_items)


@pytest.mark.asyncio
async def test_known_fees_alone_give_no_redundant_estimate_range():
    trip = TripRequest(**payload())
    places = apply_tickets([place("a", "Hoàng Thành Huế", ["museum"])], "Huế")
    draft = Draft(days=[Day(date=d, activities=[Activity(place_id="a", start_minute=480, end_minute=600)])
                        for d in (trip.start_date, trip.end_date)])
    result = await BudgetAgent().run(BudgetInput(trip=trip, draft=draft, places=PlaceResult(places=places)), Context())
    assert result.known_subtotal == Decimal(400000)
    tickets = next(line for line in result.lines if line.category == "tickets")
    assert tickets.low_vnd == tickets.high_vnd == Decimal(400000)  # a known fee, not a range
    assert result.estimate_basis  # basis still explains the fee
