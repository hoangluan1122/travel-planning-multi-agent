"""Microsoft Agent Framework engine for the planner.

Same tools, instruction and submit gate as AdkPlanner. Two MAF defaults would weaken
the gate if used as-is, so this adapter overrides both:

1. Exceptions raised by a tool are normally turned into tool-error results and fed
   back to the model, which keeps looping (fail-open). Budget breaches therefore raise
   MiddlewareFailure, the loop's fail-closed signal that aborts the run.
2. Hitting max_iterations does not raise; MAF makes one more tool-less model call and
   returns its text. A chat middleware enforces the exact model-call budget instead.
"""

import logging

from .agents import AgentError
from .planner_tools import PLANNER_INSTRUCTION, make_planner_tools

logger = logging.getLogger(__name__)

MODEL_CALL_BUDGET_MESSAGE = "Planner model-call budget exceeded"


class MafPlanner:
    """Request-isolated MAF tool loop; only validated submissions are accepted.

    client_factory returns a fresh chat client per call so iteration limits and
    middleware set here never leak between concurrent requests.
    """

    def __init__(self, client_factory, max_llm_calls=8, max_submissions=3):
        if max_llm_calls < 1 or max_submissions < 1:
            raise ValueError("Agent limits must be positive")
        self.client_factory = client_factory
        self.max_llm_calls = max_llm_calls
        self.max_submissions = max_submissions

    async def plan(self, data, context):
        from agent_framework import (
            Agent,
            ChatMiddleware,
            FunctionMiddleware,
            MiddlewareFailure,
            MiddlewareTermination,
        )

        state, inspect_trip, submit_itinerary = make_planner_tools(
            data, context, self.max_submissions, budget_error=MiddlewareFailure
        )
        max_llm_calls = self.max_llm_calls

        class StopAfterAccept(FunctionMiddleware):
            """End the loop once a draft is accepted, saving a model turn (ADK returns there too).

            Termination must come from middleware: raised inside a tool body, MAF wraps
            it as an ordinary tool error and keeps looping.
            """

            async def process(self, call_context, call_next):
                await call_next()
                if call_context.function.name == "submit_itinerary" and state.accepted is not None:
                    raise MiddlewareTermination("Itinerary accepted")

        class ModelCallBudget(ChatMiddleware):
            def __init__(self):
                self.calls = 0

            async def process(self, chat_context, call_next):
                self.calls += 1
                if self.calls > max_llm_calls:
                    raise AgentError(MODEL_CALL_BUDGET_MESSAGE)
                logger.info(
                    "agent_model_call request_id=%s call=%d", context.request_id, self.calls
                )
                await call_next()

        client = self.client_factory()
        # Backstop only: the middleware above is the authoritative limit.
        client.function_invocation_configuration["max_iterations"] = max_llm_calls
        agent = Agent(
            client,
            PLANNER_INSTRUCTION,
            name="travelmate_planner",
            tools=[inspect_trip, submit_itinerary],
            middleware=[ModelCallBudget(), StopAfterAccept()],
        )
        session = agent.create_session(session_id=str(context.request_id))
        try:
            await agent.run("Plan using tools.", session=session)
        except MiddlewareFailure as exc:
            if state.accepted is not None:
                return state.accepted
            raise AgentError(str(exc.args[0]) if exc.args else str(exc)) from None
        except AgentError:
            if state.accepted is not None:
                return state.accepted
            raise
        if state.accepted is not None:
            return state.accepted
        raise AgentError("Planner ended without a validated itinerary")
