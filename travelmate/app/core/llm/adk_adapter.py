from app.agents.itinerary_tools import PLANNER_INSTRUCTION, make_planner_tools
from app.core.base import AgentError
from app.core.llm.tool_loop import ToolLoop, run_tool_loop


class _Planner:
    """Request-isolated planner tool loop; only validated submissions are accepted."""

    engine = "adk"

    def __init__(self, model_factory, max_llm_calls=8, max_submissions=3):
        if max_llm_calls < 1 or max_submissions < 1:
            raise ValueError("Agent limits must be positive")
        self.model_factory = model_factory
        self.max_llm_calls = max_llm_calls
        self.max_submissions = max_submissions

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
        await run_tool_loop(self.engine, self.model_factory, loop, context)
        if state.accepted is None:
            raise AgentError("Planner ended without a validated itinerary")
        return state.accepted


class AdkPlanner(_Planner):
    """ADK engine. Takes an ADK model instance or model name (not a factory)."""

    engine = "adk"

    def __init__(self, model, max_llm_calls=8, max_submissions=3):
        super().__init__(lambda: model, max_llm_calls, max_submissions)
