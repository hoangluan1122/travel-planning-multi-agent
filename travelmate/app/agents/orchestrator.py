"""Classic orchestrator: runs the plan agents in order with asyncio.

memory -> place + weather (in parallel) -> recommendation -> planner -> validate -> budget.
The step rules (validate_draft, checked_places, checked_weather, plan_response) are shared
with the MAF workflow and Planning orchestrators, so all three accept and reject the same plans."""

# Cách điều phối 'classic': gọi các agent theo thứ tự bằng asyncio. File này còn chứa các luật chung mà ba
# cách điều phối cùng dùng (validate_draft, checked_places, checked_weather, plan_response).

import asyncio
from datetime import timedelta

from app.agents.plan_jobs import report as report_stage
from app.core.base import AgentError, UserError
from app.core.models import (
    BudgetInput,
    Context,
    PlannerInput,
    PlanResponse,
    RecommendationInput,
    WeatherResult,
)


# Kiểm tra lịch do LLM viết. Lịch phải có đúng từng ngày của chuyến đi theo thứ tự, chỉ dùng địa điểm có
# thật trong danh sách, không trùng giờ, không lặp địa điểm trong ngày và theo đúng ràng buộc. Sai một điều
# là từ chối.
def validate_draft(trip, draft, places, constraints=None):
    from app.core.models import ScheduleConstraints

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


# registry: danh bạ agent; mode: demo/live; timeout: giây tối đa cho mỗi agent.
class Orchestrator:
    def __init__(self, registry, mode="demo", timeout=45):
        self.registry, self.mode, self.timeout = registry, mode, timeout

    # Luồng: sở thích -> địa điểm + thời tiết (song song) -> xếp hạng -> xếp lịch -> kiểm tra -> chi phí.
    async def plan(self, trip):
        context = Context()

        async def run(name, data):
            return await self.registry.get(name).run(data, context, self.timeout)

        # Báo tiến độ cho trang (chỉ có tác dụng khi chạy trong một job).
        report_stage("places")
        memory = await run("memory", trip)
        # return_exceptions=True: một bên lỗi không huỷ bên kia; lỗi được xử lý ở
        # checked_places/checked_weather.
        results = await asyncio.gather(run("place", trip), run("weather", trip), return_exceptions=True)
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
        places = checked_places(results[0])
        weather = checked_weather(results[1])
        report_stage("ranking")
        ranked = await run("recommendation", RecommendationInput(places=places, preferences=memory))
        report_stage("scheduling")
        fallback = False
        try:
            draft = await run(
                "planner", PlannerInput(trip=trip, places=ranked, weather=weather, preferences=memory)
            )
            validate_draft(trip, draft, ranked)
        except asyncio.CancelledError:
            raise
        except Exception:
            if getattr(self.registry.get("planner"), "llm", None) is None or not ranked.places:
                raise
            # LLM xếp lịch lỗi (hết hạn mức, mất kết nối): xếp lịch theo luật để người dùng vẫn có lịch.
            from app.agents.rule_scheduler import rule_draft  # the itinerary LLM failed: schedule by rules

            draft, fallback = rule_draft(trip, ranked, weather), True
            validate_draft(trip, draft, ranked)
        report_stage("budget")
        budget = await run("budget", BudgetInput(trip=trip, draft=draft, places=ranked))
        response = plan_response(context, self.mode, draft, ranked, weather, budget, memory, places.stays)
        if fallback:
            from app.agents.planning import RULE_FALLBACK_WARNING

            response = response.model_copy(update={"warnings": [RULE_FALLBACK_WARNING, *response.warnings]})
        return response


# Step rules shared by Orchestrator and WorkflowOrchestrator, so both produce the same
# result and the same errors for the same inputs.


# Địa điểm là bắt buộc: lỗi thì dừng cả lịch trình.
def checked_places(result):
    """Place lookup is required: any failure stops the plan.

    A UserError ("Không tìm thấy địa danh ...") tells the traveller what to change, so it is
    passed on; anything else may hold provider details and becomes a generic message.
    """
    if isinstance(result, (asyncio.CancelledError, TimeoutError, UserError)):
        raise result
    if isinstance(result, BaseException):
        raise AgentError("Chưa tìm được địa điểm cho chuyến đi này. Vui lòng thử lại sau ít phút.") from result
    return result


# Thời tiết là tuỳ chọn: lỗi chỉ thành một cảnh báo.
def checked_weather(result):
    """Weather is optional: a failure becomes an explicit unverified-weather warning."""
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        return WeatherResult(warnings=["Tra cứu thời tiết thất bại; chưa xác minh thời tiết."])
    return result


# Gom kết quả các agent thành PlanResponse, gộp cảnh báo của mọi bước.
def plan_response(context, mode, draft, ranked, weather, budget, memory=None, stays=()):
    return PlanResponse(
        request_id=context.request_id,
        mode=mode,
        draft=draft,
        places=ranked.places,
        weather=weather,
        budget=budget,
        stays=list(stays),
        warnings=(memory.warnings if memory else [])
        + ranked.warnings
        + weather.warnings
        + ["Bản nháp: chưa kiểm tra giờ mở cửa hoặc tính khả thi của tuyến di chuyển."]
        # Lodging/food/transport are estimated from the reference table; warn only when they are not.
        + ([] if budget.total_high_vnd is not None else ["Chi phí chưa bao gồm đầy đủ lưu trú, ăn uống và di chuyển."]),
    )
