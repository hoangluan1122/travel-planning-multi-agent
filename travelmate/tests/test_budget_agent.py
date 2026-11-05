"""Budget agent: whole-trip estimate, verdict against the budget, savings and "what if" parsing."""

from datetime import date, timedelta
from decimal import Decimal

from app.agents import BudgetAgent
from app.chat import extract_slots, lodging_price, style_in, what_if
from app.cost_reference import reference_for
from app.models import (
    Activity,
    BudgetInput,
    Context,
    Day,
    Draft,
    Place,
    PlaceResult,
    PriceRange,
    TicketInfo,
    TripRequest,
    UserCost,
)

START = date.today() + timedelta(days=7)
TICKET = TicketInfo(group_id="hue-tu-duc", label="Vé lăng Tự Đức", adult_vnd=Decimal("150000"),
                    sources=["https://example.test/ve"], checked=date(2026, 11, 5))


def place(pid, name, **extra):
    return Place(id=pid, name=name, address="Huế", latitude=16.4, longitude=107.6, source="test", **extra)


PLACES = [
    place("tomb", "Lăng Tự Đức", ticket=TICKET),
    place("food", "Quán Bún", types=["restaurant"],
          price_range=PriceRange(low_vnd=Decimal("40000"), high_vnd=Decimal("80000"))),
    place("park", "Công viên", types=["park"], price_level="free"),
    place("hall", "Điện Khôn Thái", types=["attraction"]),  # no ticket entry, but not known to be free
]


def trip(destination="Huế", days=2, people=2, budget=5_000_000, style="mid"):
    return TripRequest(destination=destination, start_date=START, end_date=START + timedelta(days=days - 1),
                       travelers=people, budget_vnd=Decimal(budget), travel_style=style)


def draft(days=2):
    return Draft(days=[Day(date=START + timedelta(days=i), activities=[
        Activity(place_id="tomb" if i == 0 else "food", start_minute=480, end_minute=600)]) for i in range(days)])


async def estimate(t, d=None, **extra):
    data = BudgetInput(trip=t, draft=d or draft((t.end_date - t.start_date).days + 1),
                       places=PlaceResult(places=PLACES), **extra)
    return await BudgetAgent().execute(data, Context())


def money(n):
    return Decimal(n)


async def test_hue_mid_estimate_adds_reference_costs_per_room_and_person():
    b = await estimate(trip())
    lines = {line.category: line for line in b.lines}
    assert lines["tickets"].low_vnd == lines["tickets"].high_vnd == money(300000)  # 150k x 2 people
    # 1 room x 1 night x 500k-800k; food 260k x 2 people x 2 days; motorbike 50k-100k x 2 x 2.
    assert (lines["lodging"].low_vnd, lines["lodging"].high_vnd) == (money(500000), money(800000))
    assert lines["food"].low_vnd == money(1040000) and lines["transport"].high_vnd == money(400000)
    assert {line.kind for line in b.lines} == {"sourced", "reference"}
    assert all(line.sources for line in b.lines if line.kind == "reference")
    # The restaurant's own price range is inside the daily food cost, not added again.
    assert "places" not in lines
    assert b.total_low_vnd == money(300000 + 500000 + 1040000 + 200000)
    assert b.total_high_vnd == money(300000 + 800000 + 1040000 + 400000)
    assert b.per_person_high_vnd == money(1270000)
    assert b.verdict == "fits" and b.savings == []
    assert "Lưu trú" not in b.unknown_items and b.reference_checked == date(2026, 11, 5)


async def test_verdict_is_tight_or_over_and_savings_are_concrete():
    tight = await estimate(trip(budget=2_200_000))
    assert tight.verdict == "tight"
    over = await estimate(trip(budget=1_500_000))
    assert over.verdict == "over" and over.status == "incomplete"
    labels = [tip.label for tip in over.savings]
    assert "Chuyển sang mức tiết kiệm" in labels and "Bỏ Vé lăng Tự Đức" in labels
    cheaper = next(t for t in over.savings if t.label == "Chuyển sang mức tiết kiệm")
    budget_style = await estimate(trip(budget=1_500_000, style="budget"))
    assert cheaper.saving_vnd == over.total_high_vnd - budget_style.total_high_vnd
    skip = next(t for t in over.savings if t.label.startswith("Bỏ"))
    assert skip.saving_vnd == money(300000) and "Công viên" in skip.detail and "Khôn Thái" not in skip.detail
    assert [t.saving_vnd for t in over.savings] == sorted((t.saving_vnd for t in over.savings), reverse=True)


async def test_other_destinations_use_the_national_level_and_say_so():
    b = await estimate(trip(destination="Lai Châu"))
    assert b.verdict != "unknown" and b.reference_area == "Việt Nam (mức chung)"
    assert all("mức chung toàn quốc" in line.detail for line in b.lines if line.kind == "reference")
    # A city with only some figures of its own fills the rest from the national level.
    dalat = await estimate(trip(destination="Đà Lạt"))
    parts = {line.category: line for line in dalat.lines}
    assert dalat.reference_area == "Đà Lạt" and "mức chung toàn quốc" not in parts["lodging"].detail
    assert "mức chung toàn quốc" in parts["food"].detail
    assert reference_for("Hội An, Quảng Nam")[1]["id"] == "hoi-an"
    assert reference_for("TP. Hồ Chí Minh")[1]["id"] == "ho-chi-minh"


async def test_users_own_costs_still_work_without_any_reference():
    b = await estimate(trip(destination="Đà Lạt"), user_costs=[
        UserCost(category="food", label="Ăn uống", amount_vnd=500000)])
    assert next(line for line in b.lines if line.category == "food").kind == "user"


def test_every_ticket_and_city_entry_cites_a_source():
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parents[1] / "app" / "data"
    tickets = json.loads((data / "ticket_prices.json").read_text("utf-8"))["tickets"]
    assert len(tickets) >= 40 and all(t["sources"] for t in tickets)
    assert len({t["id"] for t in tickets}) == len(tickets)
    costs = json.loads((data / "cost_reference.json").read_text("utf-8"))
    items = [i for c in costs["cities"] for s in c["styles"].values() for i in s.values()]
    items += [i for s in costs["national"]["styles"].values() for i in s.values()]
    assert len(costs["cities"]) >= 10 and all(i["sources"] and i["low"] <= i["high"] for i in items)


async def test_day_trip_needs_no_room_and_user_costs_replace_reference():
    day = await estimate(trip(days=1), draft(1))
    assert "lodging" not in {line.category for line in day.lines} and day.verdict == "fits"
    own = await estimate(trip(), user_costs=[UserCost(category="lodging", label="Khách sạn đã đặt",
                                                      amount_vnd=1_000_000)])
    lodging = next(line for line in own.lines if line.category == "lodging")
    assert lodging.kind == "user" and lodging.high_vnd == money(1000000)
    assert own.known_subtotal == money(300000 + 1000000)


async def test_lodging_price_what_if_and_travelers_scale_costs():
    b = await estimate(trip(people=3), lodging_per_night_vnd=Decimal("450000"))
    lodging = next(line for line in b.lines if line.category == "lodging")
    assert lodging.high_vnd == money(900000) and "2 phòng" in lodging.detail  # 3 people need 2 rooms


async def test_high_style_costs_more_than_budget_style():
    low = await estimate(trip(style="budget"))
    high = await estimate(trip(style="high"))
    assert low.total_high_vnd < high.total_low_vnd


def test_what_if_parsing():
    assert lodging_price("nếu ở khách sạn 500k/đêm thì sao") == 500000
    assert lodging_price("phòng 1,5 triệu một đêm") == 1500000
    assert lodging_price("khách sạn 5 sao") is None and lodging_price("phòng 2 người") is None
    assert style_in("đi kiểu tiết kiệm") == "budget" and style_in("ở resort cao cấp") == "high"
    slots = extract_slots("khách sạn 1 triệu/đêm, ngân sách 5 triệu")
    assert slots.budget_vnd == 5_000_000
    changes, update, lodging = what_if("nếu đi 4 người với ngân sách 8 triệu", trip())
    assert update == {"travelers": 4, "budget_vnd": 8_000_000} and lodging is None and len(changes) == 2
    assert what_if("chi phí bao nhiêu", trip()) == ([], {}, None)


def test_landmark_tickets_match_by_city_and_free_entry_is_zero():
    from app.ticket_prices import ticket_for

    def sight(name, address):
        return Place(id=name, name=name, address=address, latitude=0, longitude=0, source="t", types=["attraction"])

    assert ticket_for(sight("Văn Miếu - Quốc Tử Giám", "Đống Đa, Hà Nội"), "Hà Nội").adult_vnd == 45000
    assert ticket_for(sight("Lăng Chủ tịch Hồ Chí Minh", "Ba Đình, Hà Nội"), "Hà Nội").adult_vnd == 0
    assert ticket_for(sight("Sun World Ba Na Hills", "Hòa Vang, Đà Nẵng"), "Đà Nẵng").adult_vnd == 900000
    assert ticket_for(sight("Dinh Độc Lập", "Quận 1, TP.HCM"), "Hồ Chí Minh").adult_vnd == 65000
    # A name in another city does not borrow its fee.
    assert ticket_for(sight("Bảo tàng Lịch sử", "Hoàn Kiếm, Hà Nội"), "Hà Nội") is None
