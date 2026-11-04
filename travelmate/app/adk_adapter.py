import logging
from contextlib import aclosing

from .agents import AgentError
from .planner_tools import PLANNER_INSTRUCTION, make_planner_tools

logger = logging.getLogger(__name__)


class AdkPlanner:
    """Request-isolated ADK tool loop; only validated submissions are accepted."""

    def __init__(self, model, max_llm_calls=8, max_submissions=3):
        if max_llm_calls < 1 or max_submissions < 1:
            raise ValueError("Agent limits must be positive")
        self.model = model
        self.max_llm_calls = max_llm_calls
        self.max_submissions = max_submissions

    async def plan(self, data, context):
        from google.adk.agents import LlmAgent
        from google.adk.agents.invocation_context import LlmCallsLimitExceededError
        from google.adk.agents.run_config import RunConfig
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        state, inspect_trip, submit_itinerary = make_planner_tools(data, context, self.max_submissions)

        agent = LlmAgent(
            name="travelmate_planner",
            model=self.model,
            instruction=PLANNER_INSTRUCTION,
            tools=[inspect_trip, submit_itinerary],
        )
        sessions = InMemorySessionService()
        session_id = str(context.request_id)
        await sessions.create_session(app_name="travelmate", user_id="request", session_id=session_id)
        runner = Runner(agent=agent, app_name="travelmate", session_service=sessions)
        try:
            async with aclosing(
                runner.run_async(
                    user_id="request",
                    session_id=session_id,
                    new_message=types.Content(role="user", parts=[types.Part(text="Plan using tools.")]),
                    run_config=RunConfig(max_llm_calls=self.max_llm_calls),
                )
            ) as events:
                async for event in events:
                    if state.accepted is not None:
                        return state.accepted
            raise AgentError("Planner ended without a validated itinerary")
        except LlmCallsLimitExceededError:
            raise AgentError("Planner model-call budget exceeded") from None
        finally:
            try:
                await runner.close()
            finally:
                await sessions.delete_session(app_name="travelmate", user_id="request", session_id=session_id)
