"""The day-scheduling LLM on Microsoft Agent Framework: a bounded tool loop that only accepts
validated drafts (app/core/llm/tool_loop.py enforces the budgets and stops on acceptance)."""

# LLM xếp lịch từng ngày, chạy trên Microsoft Agent Framework. Chỉ bản nháp đã qua kiểm tra mới được nhận.

from app.agents.itinerary_tools import PLANNER_INSTRUCTION, make_planner_tools
from app.core.base import AgentError
from app.core.llm.tool_loop import ToolLoop, run_tool_loop


# Mỗi lần plan() tạo công cụ và trạng thái mới, nên các yêu cầu không ảnh hưởng nhau.
class MafPlanner:
    """Request-isolated planner tool loop; only validated submissions are accepted.

    client_factory returns a fresh chat client per call so iteration limits and middleware set
    by the loop never leak between concurrent requests."""

    def __init__(self, client_factory, max_llm_calls=8, max_submissions=3):
        if max_llm_calls < 1 or max_submissions < 1:
            raise ValueError("Agent limits must be positive")
        self.model_factory = client_factory
        self.max_llm_calls = max_llm_calls
        self.max_submissions = max_submissions

    # Chạy vòng lặp; không có bản nháp hợp lệ thì báo lỗi.
    async def plan(self, data, context):
        state, inspect_trip, submit_itinerary = make_planner_tools(data, context, self.max_submissions)
        loop = ToolLoop(
            name="travelmate_planner",
            instruction=PLANNER_INSTRUCTION,
            tools=[inspect_trip, submit_itinerary],
            message="Plan using tools.",
            max_llm_calls=self.max_llm_calls,
            budget_message="Planner model-call budget exceeded",
            is_done=lambda: state.accepted is not None,
        )
        await run_tool_loop(self.model_factory, loop, context)
        if state.accepted is None:
            raise AgentError("Planner ended without a validated itinerary")
        return state.accepted
