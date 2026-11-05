import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from datetime import timedelta
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel

from .cost_reference import CHEAPER, PEOPLE_PER_ROOM, STYLES, reference_for
from .models import (
    Activity,
    BudgetInput,
    BudgetLine,
    BudgetResult,
    Context,
    Day,
    Draft,
    PlaceResult,
    PlannerInput,
    Preferences,
    RecommendationInput,
    SavingTip,
    TripRequest,
    WeatherResult,
)
from .telemetry import agent_span, set_outcome

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


class BaseAgent(ABC, Generic[InputT, OutputT]):
    name: str
    input_schema: type[InputT]
    output_schema: type[OutputT]

    async def run(self, data: InputT, context: Context, timeout: float = 45) -> OutputT:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Agent timeout must be finite and positive")
        # Re-validate model instances too: callers may have mutated nested fields.
        # The new model also isolates this invocation from caller-owned state.
        validated = self.input_schema.model_validate(
            data.model_dump() if isinstance(data, BaseModel) else data
        )
        request_context = Context.model_validate(context.model_dump())
        started = time.monotonic()
        outcome = "failed"
        with agent_span(self.name, request_context.request_id) as span:
            try:
                async with asyncio.timeout(timeout):
                    result = await self.execute(validated, request_context)
                    output = self.output_schema.model_validate(
                        result.model_dump() if isinstance(result, BaseModel) else result
                    )
                outcome = "success"
                return output
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except TimeoutError:
                outcome = "timeout"
                raise
            finally:
                set_outcome(span, outcome)
                self._log_run(request_context, outcome, started)

    def _log_run(self, request_context, outcome, started):
        logger.info(
            "agent_run agent=%s request=%s outcome=%s duration_ms=%d",
            self.name,
            request_context.request_id,
            outcome,
            int((time.monotonic() - started) * 1000),
        )

    @abstractmethod
    async def execute(self, data: InputT, context: Context) -> OutputT:
        raise NotImplementedError


class Registry:
    def __init__(self):
        self._agents = {}

    def register(self, agent: BaseAgent):
        if agent.name in self._agents:
            raise ValueError(f"Duplicate agent name: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        return self._agents[name]


MAX_INTERESTS = 20


class MemoryAgent(BaseAgent[TripRequest, Preferences]):
    """Request interests, plus saved preferences when the host configured a store.

    Read-only: planning never writes memory. Saving or forgetting goes through the
    memory specialist, which requires explicit user confirmation. The store is bound to
    an identity the host authenticated; nothing in the request selects whose memory
    is read.
    """

    name, input_schema, output_schema = "memory", TripRequest, Preferences

    def __init__(self, store=None):
        self.store = store  # a MemorySpecialist, or None for request-only memory

    async def execute(self, data, context):
        if self.store is None:
            return Preferences(interests=data.interests)
        from .specialists.memory import MemoryRequest

        try:
            report = await self.store.run(MemoryRequest(operation="read"), context)
        except Exception as exc:
            # Memory is optional: an unreadable store must not block planning.
            logger.warning(
                "memory_read request=%s outcome=failed error_type=%s", context.request_id, type(exc).__name__
            )
            return Preferences(
                interests=data.interests,
                warnings=["Không đọc được sở thích đã lưu; chỉ dùng sở thích trong yêu cầu này."],
            )
        seen = {interest.casefold() for interest in data.interests}
        saved = [p for p in report.preferences if p.casefold() not in seen]
        if not saved:
            return Preferences(interests=data.interests)
        merged = (list(data.interests) + saved)[:MAX_INTERESTS]
        return Preferences(
            interests=merged,
            source="request_and_saved_memory",
            warnings=[f"Đã dùng {len(merged) - len(data.interests)} sở thích đã lưu: " + ", ".join(
                merged[len(data.interests):]
            ) + "."],
        )


class PlaceAgent(BaseAgent[TripRequest, PlaceResult]):
    name, input_schema, output_schema = "place", TripRequest, PlaceResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return await self.provider.search(data)


class WeatherAgent(BaseAgent[TripRequest, WeatherResult]):
    name, input_schema, output_schema = "weather", TripRequest, WeatherResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return await self.provider.forecast(data)


class RecommendationAgent(BaseAgent[RecommendationInput, PlaceResult]):
    name, input_schema, output_schema = "recommendation", RecommendationInput, PlaceResult

    async def execute(self, data, context):
        interests = [s.casefold() for s in data.preferences.interests if s.strip()]
        ranked = sorted(
            data.places.places,
            key=lambda p: -sum(term in f"{p.name} {p.address}".casefold() for term in interests),
        )
        return PlaceResult(places=ranked, warnings=data.places.warnings)


class PlannerAgent(BaseAgent[PlannerInput, Draft]):
    name, input_schema, output_schema = "planner", PlannerInput, Draft

    def __init__(self, llm=None):
        self.llm = llm

    async def execute(self, data, context):
        if not data.places.places:
            raise AgentError("No places found; change destination or criteria")
        if self.llm is not None:
            return await self.llm.plan(data, context)
        # Explicitly demo-only schedule, not a real route optimization.
        return Draft(
            days=[
                Day(
                    date=data.trip.start_date + timedelta(days=i),
                    activities=[
                        Activity(
                            place_id=data.places.places[i % len(data.places.places)].id,
                            start_minute=540,
                            end_minute=660,
                        )
                    ],
                )
                for i in range((data.trip.end_date - data.trip.start_date).days + 1)
            ]
        )


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
                        paid.append((ticket.label, ticket.adult_vnd * people, place.id))
                        basis.append(f"{ticket.label}: {ticket.adult_vnd:,.0f} ₫/người lớn (bảng giá vé có nguồn)")
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
                    food_low += start * people
                    food_high += end * people
                    food_basis.append(f"{place.name}: {start:,.0f}–{end:,.0f} ₫/người ({day.date.isoformat()})")
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
            return BudgetLine(category=part, label=PART_LABELS[part], low_vnd=low, high_vnd=high, kind="reference",
                              detail=f"{detail}; mức {STYLES[style_name].lower()}: {item['note']}",
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
        if "food" not in covered and food_high:
            # No daily food reference: the restaurants' own price ranges are the best we have.
            lines.append(BudgetLine(category="places", label="Quán ăn trong lịch", low_vnd=food_low,
                                    high_vnd=food_high, kind="sourced", detail=f"{people} người, khoảng giá nguồn"))
        if "food" not in covered:
            basis.extend(food_basis)
        elif food_basis:
            basis.append("Giá các quán trong lịch đã nằm trong khoản ăn uống mỗi ngày.")

        unknown = [label for part, label in COVERED.items() if part not in covered]
        unknown += [label for place, label in unknown_places
                    if not ("food" in covered and FOOD_TYPES & set(place.types))]
        ranged = bool(ticket_high or food_high)
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
            estimated_low_vnd=total_low if has_estimate else (known + ticket_low + food_low if ranged else None),
            estimated_high_vnd=total_high if has_estimate else (known + ticket_high + food_high if ranged else None),
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
