"""Planner with deterministic routing post-validation, not multi-agent delegation."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..agents import AgentError, BaseAgent
from ..models import Draft, Model, PlannerInput
from .planner import PlannerSpecialist
from .routing import OSRMProvider, Precedence, RoutePoint, RouteReport, RouteRequest, Visit, calculate_route


class VisitWindow(Model):
    opens_minute: int = Field(ge=0, le=1439)
    closes_minute: int = Field(ge=1, le=1440)
    source: str = Field(min_length=1, max_length=300)


class DayConstraints(Model):
    date: date
    origin: RoutePoint
    departure_minute: int = Field(default=540, ge=0, le=1439)
    finish_by_minute: int = Field(default=1080, ge=1, le=1440)
    return_to_origin: bool = True
    windows: dict[str, VisitWindow] = Field(default_factory=dict)
    destination: RoutePoint | None = None
    travel_buffer_minutes: int = Field(default=0, ge=0, le=120, strict=True)
    optimize_order: bool = Field(default=True, strict=True)
    include_geometry: bool = Field(default=False, strict=True)
    fixed_starts: dict[str, Annotated[int, Field(ge=0, le=1439, strict=True)]] = Field(default_factory=dict)
    precedence: list[Precedence] = Field(default_factory=list, max_length=28)


class RoutedPlannerInput(PlannerInput):
    route_days: list[DayConstraints] = Field(min_length=1, max_length=14)

    @model_validator(mode="after")
    def route_dates(self):
        from datetime import timedelta

        expected = [
            self.trip.start_date + timedelta(days=i)
            for i in range((self.trip.end_date - self.trip.start_date).days + 1)
        ]
        if [d.date for d in self.route_days] != expected:
            raise ValueError("Route constraints must cover each trip day exactly in order")
        for day in self.route_days:
            if day.departure_minute >= day.finish_by_minute:
                raise ValueError("Invalid daily route bounds")
            if max(day.departure_minute, self.constraints.day_start_minute) >= min(
                day.finish_by_minute, self.constraints.day_end_minute
            ):
                raise ValueError("Route bounds conflict with schedule bounds")
            if not set(day.windows) <= {p.id for p in self.places.places}:
                raise ValueError("Route windows must refer to supplied places")
            if not set(day.fixed_starts) <= {p.id for p in self.places.places}:
                raise ValueError("Appointments must refer to supplied places")
            for place_id, window in day.windows.items():
                if window.opens_minute >= window.closes_minute:
                    raise ValueError("Invalid visit window")
                general = self.constraints.visit_windows.get(place_id)
                if general and max(general.opens_minute, window.opens_minute) >= min(
                    general.closes_minute, window.closes_minute
                ):
                    raise ValueError("Route and schedule visit windows conflict")
        return self


class RoutedDay(Model):
    date: date
    route: RouteReport
    unverified_window_ids: list[str]
    supplied_window_sources: dict[str, str]


class RoutedPlan(Model):
    status: Literal["route_feasible_draft", "infeasible"]
    original_draft: Draft
    days: list[RoutedDay]
    warnings: list[str]


async def route_draft(data: RoutedPlannerInput, draft: Draft, provider):
    from ..orchestrator import validate_draft

    validate_draft(data.trip, draft, data.places, data.constraints)
    places = {p.id: p for p in data.places.places}
    days = []
    for day, limits in zip(draft.days, data.route_days, strict=True):
        visits = []
        unknown = []
        sources = {}
        if not set(limits.fixed_starts) <= {activity.place_id for activity in day.activities}:
            raise AgentError("Draft omitted a fixed appointment for this day")
        for activity in day.activities:
            place = places[activity.place_id]
            window = limits.windows.get(place.id)
            general = data.constraints.visit_windows.get(place.id)
            windows = [w for w in (window, general) if w is not None]
            if not windows:
                unknown.append(place.id)
            else:
                sources[place.id] = " | ".join(dict.fromkeys(w.source for w in windows))
            visits.append(
                Visit(
                    id=place.id,
                    latitude=place.latitude,
                    longitude=place.longitude,
                    duration_minutes=activity.end_minute - activity.start_minute,
                    opens_minute=max((w.opens_minute for w in windows), default=0),
                    closes_minute=min((w.closes_minute for w in windows), default=1440),
                    fixed_start_minute=limits.fixed_starts.get(place.id),
                )
            )
        if len({v.id for v in visits}) != len(visits):
            raise AgentError("Repeated visits in one day require occurrence-aware routing")
        request = RouteRequest(
            origin=limits.origin,
            visits=visits,
            departure_minute=max(limits.departure_minute, data.constraints.day_start_minute),
            finish_by_minute=min(limits.finish_by_minute, data.constraints.day_end_minute),
            return_to_origin=limits.return_to_origin,
            destination=limits.destination,
            travel_buffer_minutes=limits.travel_buffer_minutes,
            optimize_order=limits.optimize_order,
            include_geometry=limits.include_geometry,
            precedence=limits.precedence,
        )
        report = await calculate_route(request, provider)
        days.append(
            RoutedDay(
                date=day.date,
                route=report,
                unverified_window_ids=unknown,
                supplied_window_sources=sources,
            )
        )
    return RoutedPlan(
        status="route_feasible_draft" if all(d.route.status == "feasible" for d in days) else "infeasible",
        original_draft=draft,
        days=days,
        warnings=[
            "Dùng lịch theo giây trong days[].route.schedule; original_draft chỉ là bản LLM trước tối ưu.",
            "Chưa xác minh giờ mở cửa thiếu nguồn; không phải xác nhận chuyến đi thực tế.",
            "Giữ nguyên tập điểm và thời lượng từng ngày; không tự bỏ điểm hay phân lại ngày.",
        ],
    )


class RoutedPlannerSpecialist(BaseAgent[RoutedPlannerInput, RoutedPlan]):
    name, input_schema, output_schema = "routed_planner", RoutedPlannerInput, RoutedPlan

    def __init__(self, model_factory, provider=None):
        self.model_factory, self.provider = model_factory, provider or OSRMProvider()

    async def execute(self, data, context):
        plain = PlannerInput(
            trip=data.trip, places=data.places, weather=data.weather, constraints=data.constraints
        )
        draft = await PlannerSpecialist(self.model_factory).execute(plain, context)
        return await route_draft(data, draft, self.provider)
