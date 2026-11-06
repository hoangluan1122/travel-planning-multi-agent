"""Budget agent: whole-trip cost against the budget, with savings when it does not fit."""

import math
from decimal import Decimal

from app.core.base import BaseAgent
from app.core.models import BudgetInput, BudgetLine, BudgetResult, SavingTip
from app.tools.prices.cost_reference import CHEAPER, PEOPLE_PER_ROOM, STYLES, reference_for

FOOD_TYPES = {"restaurant", "cafe", "fast_food", "food_court", "food", "bar"}
COVERED = {"lodging": "Lưu trú", "food": "Ăn uống", "transport": "Di chuyển"}
PART_LABELS = {"lodging": "Lưu trú", "food": "Ăn uống", "transport": "Di chuyển tại chỗ", "other": "Khoản khác"}


def vnd(value):
    return f"{Decimal(value):,.0f} ₫".replace(",", ".")


class BudgetAgent(BaseAgent[BudgetInput, BudgetResult]):
    """Whole-trip cost estimate against the budget, with savings when it does not fit.

    Numbers come from three places, kept apart in `lines`: sourced entrance fees and restaurant
    price ranges (sourced), the cited reference table for lodging/food/transport by travel style
    (reference), and costs the user typed (user). Without reference costs for the city and without
    the user's own, lodging/food/transport stay unknown and the verdict is "unknown", never a guess.
    """

    name, input_schema, output_schema = "budget", BudgetInput, BudgetResult

    async def execute(self, data, context):
        trip = data.trip
        people = trip.travelers
        style = getattr(trip, "travel_style", None) or "mid"
        places = {p.id: p for p in data.places.places}
        known = Decimal("0")  # sourced fixed fees (tickets, demo visit costs)
        ticket_low = ticket_high = Decimal("0")
        food_low = food_high = Decimal("0")
        other_low = other_high = Decimal("0")  # non-food places with a source price range
        basis, food_basis, paid = [], [], []
        tickets_seen = set()
        unknown_places = []
        for day in data.draft.days:
            for activity in day.activities:
                place = places[activity.place_id]
                if place.estimated_visit_cost_vnd is not None:
                    cost = place.estimated_visit_cost_vnd * people
                    known += cost
                    if cost:
                        paid.append((place.name, cost, place.id))
                    continue
                ticket = place.ticket
                if ticket:
                    # One ticket per group per trip (e.g. a single Imperial City ticket).
                    if ticket.group_id in tickets_seen:
                        continue
                    tickets_seen.add(ticket.group_id)
                    if ticket.adult_vnd is not None:
                        known += ticket.adult_vnd * people
                        if ticket.adult_vnd:
                            paid.append((ticket.label, ticket.adult_vnd * people, place.id))
                            basis.append(f"{ticket.label}: {ticket.adult_vnd:,.0f} ₫/người lớn (bảng giá vé có nguồn)")
                        else:
                            basis.append(f"{ticket.label}: miễn phí (bảng giá vé có nguồn)")
                        continue
                    if ticket.low_vnd is not None or ticket.high_vnd is not None:
                        start = ticket.low_vnd if ticket.low_vnd is not None else ticket.high_vnd
                        end = ticket.high_vnd if ticket.high_vnd is not None else ticket.low_vnd
                        ticket_low += start * people
                        ticket_high += end * people
                        paid.append((ticket.label, end * people, place.id))
                        basis.append(f"{ticket.label}: {start:,.0f}–{end:,.0f} ₫/người (bảng giá vé có nguồn)")
                        continue
                span = place.price_range
                if span and (span.low_vnd is not None or span.high_vnd is not None):
                    # A source price range per person; an estimate, never added to known costs.
                    start = span.low_vnd if span.low_vnd is not None else span.high_vnd
                    end = span.high_vnd if span.high_vnd is not None else span.low_vnd
                    entry = f"{place.name}: {start:,.0f}–{end:,.0f} ₫/người ({day.date.isoformat()})"
                    if FOOD_TYPES & set(place.types):
                        food_low += start * people
                        food_high += end * people
                        food_basis.append(entry)
                    else:  # a paid activity with a price range: never part of the daily food cost
                        other_low += start * people
                        other_high += end * people
                        basis.append(entry)
                else:
                    unknown_places.append((place, f"Chi phí tại {place.name} ({day.date.isoformat()})"))

        days = (trip.end_date - trip.start_date).days + 1
        nights = days - 1
        rooms = math.ceil(people / PEOPLE_PER_ROOM)
        checked, city = reference_for(trip.destination)
        user = {}
        for cost in data.user_costs:
            user.setdefault(cost.category, []).append(cost)

        lines = []
        if known or ticket_high:
            lines.append(BudgetLine(category="tickets", label="Vé tham quan", low_vnd=known + ticket_low,
                                    high_vnd=known + ticket_high, kind="sourced",
                                    detail=f"{people} người, bảng giá vé có nguồn"))
        covered = set()

        def reference_line(part, item, style_name, low, high, detail):
            # A city without its own figure for this part uses the country-wide level; say so.
            scope = "mức chung toàn quốc, " if item.get("national") else ""
            return BudgetLine(category=part, label=PART_LABELS[part], low_vnd=low, high_vnd=high, kind="reference",
                              detail=f"{detail}; {scope}mức {STYLES[style_name].lower()}: {item['note']}",
                              sources=item["sources"][:5])

        def reference_parts(style_name):
            out = {}
            if nights and data.lodging_per_night_vnd is not None:
                price = data.lodging_per_night_vnd
                out["lodging"] = BudgetLine(
                    category="lodging", label=PART_LABELS["lodging"], low_vnd=price * rooms * nights,
                    high_vnd=price * rooms * nights, kind="user",
                    detail=f"{rooms} phòng × {nights} đêm × {vnd(price)} (giá bạn đưa ra)")
            if city is None:
                return out
            ref = city["styles"][style_name]
            if nights:
                if "lodging" not in out:
                    item = ref["lodging"]
                    out["lodging"] = reference_line(
                        "lodging", item, style_name, item["low"] * rooms * nights, item["high"] * rooms * nights,
                        f"{rooms} phòng × {nights} đêm × {vnd(item['low'])}–{vnd(item['high'])}")
            for part in ("food", "transport"):
                item = ref[part]
                out[part] = reference_line(
                    part, item, style_name, item["low"] * people * days, item["high"] * people * days,
                    f"{people} người × {days} ngày × {vnd(item['low'])}"
                    + (f"–{vnd(item['high'])}" if item["high"] != item["low"] else ""))
            return out

        parts = reference_parts(style)
        if not nights:
            covered.add("lodging")  # a day trip needs no room
        for part in ("lodging", "food", "transport", "other"):
            if part in user:
                amount = sum(c.amount_vnd for c in user[part])
                lines.append(BudgetLine(category=part, label=PART_LABELS[part], low_vnd=Decimal(amount),
                                        high_vnd=Decimal(amount), kind="user",
                                        detail="; ".join(f"{c.label}: {vnd(c.amount_vnd)}" for c in user[part])))
                covered.add(part)
                known += amount
                basis.extend(f"{c.label}: {vnd(c.amount_vnd)} (do bạn nhập)" for c in user[part])
            elif part in parts:
                lines.append(parts[part])
                covered.add(part)
        place_low, place_high = other_low, other_high
        if "food" not in covered:
            # No daily food cost: the restaurants' own price ranges are the best we have.
            place_low, place_high = place_low + food_low, place_high + food_high
        if place_high:
            lines.append(BudgetLine(category="places", label="Địa điểm có khoảng giá", low_vnd=place_low,
                                    high_vnd=place_high, kind="sourced", detail=f"{people} người, khoảng giá nguồn"))
        if "food" not in covered:
            basis.extend(food_basis)
        elif food_basis:
            basis.append("Giá các quán trong lịch đã nằm trong khoản ăn uống mỗi ngày.")

        unknown = [label for part, label in COVERED.items() if part not in covered]
        unknown += [label for place, label in unknown_places
                    if not ("food" in covered and FOOD_TYPES & set(place.types))]
        ranged = bool(ticket_high or food_high or other_high)
        complete = {"lodging", "food", "transport"} <= covered
        total_low = sum((line.low_vnd for line in lines), Decimal("0"))
        total_high = sum((line.high_vnd for line in lines), Decimal("0"))
        cap = trip.budget_vnd
        verdict = "unknown"
        if complete:
            verdict = "fits" if total_high <= cap else "tight" if total_low <= cap else "over"
        elif total_low > cap:
            verdict = "over"  # already over without the unknown parts
        status = "over_budget" if known > cap else ("within_budget" if verdict == "fits" and not unknown
                                                    else "incomplete")
        savings = []
        if verdict in ("tight", "over"):
            savings = self.savings(style, reference_parts, user, paid, data, total_high - cap)
        has_estimate = bool(lines) and (complete or ranged)
        return BudgetResult(
            known_subtotal=known,
            unknown_items=unknown,
            status=status,
            estimated_low_vnd=total_low if has_estimate else (
                known + ticket_low + food_low + other_low if ranged else None),
            estimated_high_vnd=total_high if has_estimate else (
                known + ticket_high + food_high + other_high if ranged else None),
            estimate_basis=basis,
            travel_style=style,
            budget_vnd=cap,
            lines=lines,
            total_low_vnd=total_low if complete else None,
            total_high_vnd=total_high if complete else None,
            per_person_high_vnd=(total_high / people).quantize(Decimal("1")) if complete else None,
            verdict=verdict,
            savings=savings,
            reference_checked=checked if city else None,
            reference_area=city["label"] if city else None,
        )

    @staticmethod
    def savings(style, reference_parts, user, paid, data, over):
        """Concrete cuts off the high estimate, biggest first; none is applied automatically."""
        tips = []
        cheaper = CHEAPER.get(style)
        if cheaper:
            now, then = reference_parts(style), reference_parts(cheaper)
            saved = sum((now[p].high_vnd - then[p].high_vnd for p in now if p not in user and p in then),
                        Decimal("0"))
            if saved > 0:
                tips.append(SavingTip(label=f"Chuyển sang mức {STYLES[cheaper].lower()}",
                                      detail="Chỗ ở, ăn uống và đi lại theo giá tham khảo mức "
                                             f"{STYLES[cheaper].lower()}.", saving_vnd=saved))
            if "lodging" in now and "lodging" in then and now["lodging"].kind == "reference" and "lodging" not in user:
                cut = now["lodging"].high_vnd - then["lodging"].high_vnd
                if 0 < cut < saved:
                    tips.append(SavingTip(label=f"Chỉ hạ chỗ ở xuống mức {STYLES[cheaper].lower()}",
                                          detail="Giữ ăn uống và đi lại như cũ.", saving_vnd=cut))
        used = {a.place_id for d in data.draft.days for a in d.activities}
        # Only places the source itself marks as free; "no ticket in our table" is not "free"
        # (a hall inside the Imperial City has no entry of its own but needs the ticket).
        free = [p.name for p in data.places.places
                if p.id not in used and p.price_level == "free" and not p.ticket
                and not (FOOD_TYPES & set(p.types))][:2]
        for label, cost, _ in sorted(paid, key=lambda item: -item[1])[:3]:
            swap = f" Có thể thay bằng {', '.join(free)} (nguồn ghi miễn phí)." if free else ""
            tips.append(SavingTip(label=f"Bỏ {label}", detail=f"Bớt một điểm có vé.{swap}", saving_vnd=cost))
        tips.sort(key=lambda t: -t.saving_vnd)
        if over > 0 and tips and tips[0].saving_vnd >= over:
            tips[0].detail += " Riêng cách này đã đủ để vừa ngân sách."
        return tips[:4]
