"""The agent shell every TravelMate agent runs in.

BaseAgent.run re-validates the input, enforces a timeout, validates the output against the
agent's schema, and records telemetry and one log line per run. An agent only writes execute().
"""

# Khung chung của mọi agent. Một agent chỉ cần khai báo tên, schema đầu vào/đầu ra và viết execute();
# BaseAgent.run() lo phần còn lại: kiểm tra dữ liệu, giới hạn thời gian, ghi log và telemetry.

import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.core.models import Context
from app.core.telemetry import agent_span, set_outcome

# Kiểu tổng quát: mỗi agent có kiểu đầu vào và đầu ra riêng (BaseAgent[Vào, Ra]).
InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
logger = logging.getLogger(__name__)


# Lỗi nghiệp vụ của agent (nguồn lỗi, vượt giới hạn...). API đổi nó thành mã 502.
class AgentError(Exception):
    pass


# Lỗi có câu thông báo viết sẵn cho người dùng, được hiển thị nguyên văn.
class UserError(AgentError):
    """An error whose message is written for the traveller (in Vietnamese) and is shown as is,
    e.g. a destination that was not found. Other errors get a generic message instead."""


# Lớp cha của mọi agent. name: tên agent; input_schema/output_schema: model Pydantic dùng để kiểm tra dữ
# liệu vào/ra.
class BaseAgent(ABC, Generic[InputT, OutputT]):
    name: str
    input_schema: type[InputT]
    output_schema: type[OutputT]

    # Cách DUY NHẤT để gọi một agent. Thứ tự: kiểm tra timeout -> kiểm tra lại đầu vào -> chạy execute()
    # trong giới hạn thời gian -> kiểm tra đầu ra -> ghi kết quả (thành công/lỗi/quá giờ).
    async def run(self, data: InputT, context: Context, timeout: float = 45) -> OutputT:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Agent timeout must be finite and positive")
        # Re-validate model instances too: callers may have mutated nested fields.
        # The new model also isolates this invocation from caller-owned state.
        # Tạo bản sao đã kiểm tra: agent không sửa được dữ liệu của người gọi.
        validated = self.input_schema.model_validate(
            data.model_dump() if isinstance(data, BaseModel) else data
        )
        request_context = Context.model_validate(context.model_dump())
        started = time.monotonic()
        outcome = "failed"
        with agent_span(self.name, request_context.request_id) as span:
            try:
                # Quá thời gian thì asyncio huỷ execute() và ném TimeoutError.
                async with asyncio.timeout(timeout):
                    result = await self.execute(validated, request_context)
                    # Đầu ra sai schema là lỗi, không được đi tiếp.
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

    # Một dòng log cho mỗi lần chạy: tên agent, mã yêu cầu, kết quả, thời gian (ms).
    def _log_run(self, request_context, outcome, started):
        logger.info(
            "agent_run agent=%s request=%s outcome=%s duration_ms=%d",
            self.name,
            request_context.request_id,
            outcome,
            int((time.monotonic() - started) * 1000),
        )

    # Phần việc riêng của từng agent; lớp con bắt buộc phải viết.
    @abstractmethod
    async def execute(self, data: InputT, context: Context) -> OutputT:
        raise NotImplementedError


# Danh bạ agent theo tên; orchestrator lấy agent từ đây (registry.get('place')).
class Registry:
    def __init__(self):
        self._agents = {}

    # Không cho đăng ký hai agent trùng tên.
    def register(self, agent: BaseAgent):
        if agent.name in self._agents:
            raise ValueError(f"Duplicate agent name: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        return self._agents[name]
