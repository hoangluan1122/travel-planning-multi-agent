"""The agent shell every TravelMate agent runs in.

BaseAgent.run re-validates the input, enforces a timeout, validates the output against the
agent's schema, and records telemetry and one log line per run. An agent only writes execute().
"""

import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.core.models import Context
from app.core.telemetry import agent_span, set_outcome

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
