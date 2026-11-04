import asyncio
from datetime import timedelta

from .agents import AgentError
from .models import BudgetInput, Context, PlannerInput, PlanResponse, RecommendationInput, WeatherResult


def validate_draft(trip, draft, places, constraints=None):
    from .models import ScheduleConstraints

    constraints = constraints or ScheduleConstraints()
    expected = [
        trip.start_date + timedelta(days=i) for i in range((trip.end_date - trip.start_date).days + 1)
    ]
    if [day.date for day in draft.days] != expected:
        raise AgentError("Planner returned missing, duplicate or unordered days")
    known = {p.id for p in places.places}
    visited = set()
    for day in draft.days:
        if len(day.activities) > constraints.max_activities_per_day:
            raise AgentError("Too many activities in one day")
        daily_ids = set()
        last_end = 0
        for item in day.activities:
            if item.place_id not in known:
                raise AgentError("Planner invented an unknown place")
            if item.start_minute < last_end:
                raise AgentError("Planner returned overlapping activities")
            if item.place_id in daily_ids:
                raise AgentError("Planner repeated a place within one sightseeing day")
            if item.place_id in constraints.excluded_place_ids:
                raise AgentError("Planner selected an excluded place")
            if (
                item.start_minute < constraints.day_start_minute
                or item.end_minute > constraints.day_end_minute
            ):
                raise AgentError("Activity falls outside the allowed daily window")
            if item.end_minute - item.start_minute < constraints.min_activity_minutes:
                raise AgentError("Activity is shorter than minimum visit duration")
            window = constraints.visit_windows.get(item.place_id)
            if window and (item.start_minute < window.opens_minute or item.end_minute > window.closes_minute):
                raise AgentError("Activity falls outside the supplied visit window")
            daily_ids.add(item.place_id)
            visited.add(item.place_id)
            last_end = item.end_minute
    if not set(constraints.required_place_ids) <= visited:
        raise AgentError("Planner omitted required places")


class Orchestrator:
    def __init__(self, registry, mode="demo", timeout=45):
        self.registry, self.mode, self.timeout = registry, mode, timeout

    async def plan(self, trip):
        context = Context()

        async def run(name, data):
            return await self.registry.get(name).run(data, context, self.timeout)

        memory = await run("memory", trip)
        results = await asyncio.gather(run("place", trip), run("weather", trip), return_exceptions=True)
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
        places = checked_places(results[0])
        weather = checked_weather(results[1])
        ranked = await run("recommendation", RecommendationInput(places=places, preferences=memory))
        draft = await run(
            "planner", PlannerInput(trip=trip, places=ranked, weather=weather, preferences=memory)
        )
        validate_draft(trip, draft, ranked)
        budget = await run("budget", BudgetInput(trip=trip, draft=draft, places=ranked))
        return plan_response(context, self.mode, draft, ranked, weather, budget, memory)


# Step rules shared by Orchestrator and WorkflowOrchestrator, so both produce the same
# result and the same errors for the same inputs.


def checked_places(result):
    """Place lookup is required: any failure stops the plan."""
    if isinstance(result, (asyncio.CancelledError, TimeoutError)):
        raise result
    if isinstance(result, BaseException):
        raise AgentError("Place lookup failed; no reliable candidates available") from result
    return result


def checked_weather(result):
    """Weather is optional: a failure becomes an explicit unverified-weather warning."""
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        return WeatherResult(warnings=["Tra cứu thời tiết thất bại; chưa xác minh thời tiết."])
    return result


def plan_response(context, mode, draft, ranked, weather, budget, memory=None):
    return PlanResponse(
        request_id=context.request_id,
        mode=mode,
        draft=draft,
        places=ranked.places,
        weather=weather,
        budget=budget,
        warnings=(memory.warnings if memory else [])
        + ranked.warnings
        + weather.warnings
        + [
            "Bản nháp: chưa kiểm tra giờ mở cửa hoặc tính khả thi của tuyến di chuyển.",
            "Chi phí chưa bao gồm đầy đủ lưu trú, ăn uống và di chuyển.",
        ],
    )
