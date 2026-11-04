import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from datetime import timedelta
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel

from .models import (
    Activity,
    BudgetInput,
    BudgetResult,
    Context,
    Day,
    Draft,
    PlaceResult,
    PlannerInput,
    Preferences,
    RecommendationInput,
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


class BudgetAgent(BaseAgent[BudgetInput, BudgetResult]):
    name, input_schema, output_schema = "budget", BudgetInput, BudgetResult

    async def execute(self, data, context):
        places = {p.id: p for p in data.places.places}
        total = Decimal("0")
        low = high = Decimal("0")
        basis = []
        tickets_seen = set()
        ranged = False  # only show an estimate when some cost is a range, not just known fees
        unknown = ["Lưu trú", "Ăn uống", "Di chuyển"]
        for day in data.draft.days:
            for activity in day.activities:
                place = places[activity.place_id]
                if place.estimated_visit_cost_vnd is not None:
                    total += place.estimated_visit_cost_vnd * data.trip.travelers
                    continue
                ticket = place.ticket
                if ticket:
                    # One ticket per group per trip (e.g. a single Imperial City ticket).
                    if ticket.group_id in tickets_seen:
                        continue
                    tickets_seen.add(ticket.group_id)
                    if ticket.adult_vnd is not None:
                        total += ticket.adult_vnd * data.trip.travelers
                        basis.append(f"{ticket.label}: {ticket.adult_vnd:,.0f} ₫/người lớn (bảng giá vé có nguồn)")
                        continue
                    if ticket.low_vnd is not None or ticket.high_vnd is not None:
                        start = ticket.low_vnd if ticket.low_vnd is not None else ticket.high_vnd
                        end = ticket.high_vnd if ticket.high_vnd is not None else ticket.low_vnd
                        low += start * data.trip.travelers
                        high += end * data.trip.travelers
                        ranged = True
                        basis.append(f"{ticket.label}: {start:,.0f}–{end:,.0f} ₫/người (bảng giá vé có nguồn)")
                        continue
                span = place.price_range
                if span and (span.low_vnd is not None or span.high_vnd is not None):
                    # A source price range per person; an estimate, never added to known costs.
                    start = span.low_vnd if span.low_vnd is not None else span.high_vnd
                    end = span.high_vnd if span.high_vnd is not None else span.low_vnd
                    low += start * data.trip.travelers
                    high += end * data.trip.travelers
                    ranged = True
                    basis.append(f"{place.name}: {start:,.0f}–{end:,.0f} ₫/người ({day.date.isoformat()})")
                else:
                    unknown.append(f"Chi phí tại {place.name} ({day.date.isoformat()})")
        status = "over_budget" if total > data.trip.budget_vnd else "incomplete"
        return BudgetResult(
            known_subtotal=total,
            unknown_items=unknown,
            status=status,
            estimated_low_vnd=total + low if ranged else None,
            estimated_high_vnd=total + high if ranged else None,
            estimate_basis=basis,
        )
