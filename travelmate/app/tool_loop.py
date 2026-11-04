"""One bounded tool loop, two runtimes (Google ADK and Microsoft Agent Framework).

Agents define their tools, instruction and acceptance state once. Tools signal a
breached budget by raising AgentError and record an accepted result in their own
state; is_done() reports whether that happened. Both runtimes then guarantee:

- an AgentError from a tool aborts the run (never fed back to the model),
- at most max_llm_calls model calls, then AgentError(budget_message),
- the loop stops as soon as is_done() is true, without another model turn.

The caller reads its accepted result after run_tool_loop returns.
"""

import logging
from contextlib import aclosing
from dataclasses import dataclass
from typing import Callable, Literal

from .agents import AgentError

logger = logging.getLogger(__name__)

Engine = Literal["adk", "maf"]


@dataclass
class ToolLoop:
    name: str
    instruction: str
    tools: list[Callable]
    message: str
    max_llm_calls: int
    budget_message: str
    is_done: Callable[[], bool]


async def run_tool_loop(engine: Engine, model_factory, loop: ToolLoop, context) -> None:
    """model_factory returns an ADK model (engine adk) or a MAF chat client (engine maf)."""
    if loop.max_llm_calls < 1:
        raise ValueError("max_llm_calls must be positive")
    if engine == "maf":
        await _run_maf(model_factory, loop, context)
    elif engine == "adk":
        await _run_adk(model_factory, loop, context)
    else:
        raise ValueError(f"Unknown agent engine: {engine}")


async def _run_adk(model_factory, loop, context):
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = LlmAgent(name=loop.name, model=model_factory(), instruction=loop.instruction, tools=loop.tools)
    sessions = InMemorySessionService()
    session_id = str(context.request_id)
    await sessions.create_session(app_name=loop.name, user_id="request", session_id=session_id)
    runner = Runner(agent=agent, app_name=loop.name, session_service=sessions)
    try:
        async with aclosing(
            runner.run_async(
                user_id="request",
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=loop.message)]),
                run_config=RunConfig(max_llm_calls=loop.max_llm_calls),
            )
        ) as events:
            async for _ in events:
                if loop.is_done():
                    return
    except LlmCallsLimitExceededError:
        raise AgentError(loop.budget_message) from None
    finally:
        try:
            await runner.close()
        finally:
            await sessions.delete_session(app_name=loop.name, user_id="request", session_id=session_id)


async def _run_maf(client_factory, loop, context):
    """MAF defaults differ from ADK in three ways; the middleware below restores the guarantees.

    1. A tool exception becomes a tool-error result and the loop continues (fail-open).
       FailClosedTools re-raises AgentError as MiddlewareFailure, which aborts the run.
    2. Hitting max_iterations makes one extra tool-less model call instead of raising.
       ModelCallBudget counts calls and raises at max_llm_calls + 1.
    3. MiddlewareTermination only ends the loop when raised from middleware, not from a
       tool body. FailClosedTools raises it once is_done() is true.
    """
    from agent_framework import (
        Agent,
        ChatMiddleware,
        FunctionMiddleware,
        MiddlewareFailure,
        MiddlewareTermination,
    )

    class ModelCallBudget(ChatMiddleware):
        def __init__(self):
            self.calls = 0

        async def process(self, chat_context, call_next):
            self.calls += 1
            if self.calls > loop.max_llm_calls:
                raise AgentError(loop.budget_message)
            await call_next()

    class FailClosedTools(FunctionMiddleware):
        async def process(self, call_context, call_next):
            name = call_context.function.name
            try:
                await call_next()
            except AgentError as exc:
                logger.info(
                    "agent_tool request_id=%s agent=%s tool=%s outcome=aborted",
                    context.request_id,
                    loop.name,
                    name,
                )
                raise MiddlewareFailure(str(exc)) from exc
            logger.info(
                "agent_tool request_id=%s agent=%s tool=%s outcome=ok", context.request_id, loop.name, name
            )
            if loop.is_done():
                raise MiddlewareTermination(f"{loop.name} accepted output")

    client = client_factory()
    # Backstop only: ModelCallBudget is the authoritative limit.
    client.function_invocation_configuration["max_iterations"] = loop.max_llm_calls
    agent = Agent(
        client,
        loop.instruction,
        name=loop.name,
        tools=loop.tools,
        middleware=[ModelCallBudget(), FailClosedTools()],
    )
    try:
        await agent.run(loop.message, session=agent.create_session(session_id=str(context.request_id)))
    except MiddlewareFailure as exc:
        if loop.is_done():
            return
        cause = exc.__cause__
        raise (cause if isinstance(cause, AgentError) else AgentError(str(exc))) from None
    except AgentError:
        if loop.is_done():
            return
        raise
