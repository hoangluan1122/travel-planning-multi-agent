"""One bounded tool loop on Microsoft Agent Framework (MAF), the only agent runtime.

Agents define their tools, instruction and acceptance state once. Tools signal a
breached budget by raising AgentError and record an accepted result in their own
state; is_done() reports whether that happened. The loop then guarantees:

- an AgentError from a tool aborts the run (never fed back to the model),
- at most max_llm_calls model calls, then AgentError(budget_message),
- the loop stops as soon as is_done() is true, without another model turn.

The caller reads its accepted result after run_tool_loop returns.
"""

# Vòng lặp 'model gọi công cụ' dùng chung cho mọi agent LLM. Model đọc hướng dẫn, gọi công cụ (tool), nhận
# kết quả, gọi tiếp... đến khi một công cụ chấp nhận bài nộp (is_done() = True). Chạy trên Microsoft Agent
# Framework, với ba đảm bảo: lỗi công cụ dừng vòng lặp, giới hạn số lần gọi model, dừng ngay khi đã có kết quả.

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from app.core.base import AgentError

logger = logging.getLogger(__name__)


# Mô tả một vòng lặp: tên, hướng dẫn cho model, danh sách công cụ, câu hỏi đầu tiên, số lần gọi model tối
# đa, thông báo khi vượt giới hạn, hàm báo 'đã xong'.
@dataclass
class ToolLoop:
    name: str
    instruction: str
    tools: list[Callable]
    message: str
    max_llm_calls: int
    budget_message: str
    is_done: Callable[[], bool]


# Mã lỗi tạm thời đáng thử lại: 429 (quá hạn mức) và 5xx (máy chủ lỗi).
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS_S = (2.0, 5.0)  # provider 5xx come in short bursts; back off a little more each time
RATE_LIMIT_DELAYS_S = (10.0, 20.0)  # 429 quotas are per minute, so wait longer


# Lần theo chuỗi lỗi xem có phải lỗi 429 của Gemini không (tối đa 10 tầng).
def is_rate_limited(exc):
    seen = 0
    while exc is not None and seen < 10:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code == 429:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


# Lỗi tạm thời (mạng, 5xx, 429) thì thử lại; lỗi nghiệp vụ (AgentError) thì không.
def is_transient(exc):
    """A provider hiccup worth one retry: 5xx/429 from the model API or a network timeout.

    Walks the cause chain because MAF wraps provider errors. Budget breaches and
    other AgentErrors are never transient.
    """
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, AgentError):
            return False
        name = type(exc).__name__
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if name == "ServerError" or (isinstance(code, int) and code in TRANSIENT_STATUS):
            return True
        if name in {"ReadTimeout", "ConnectTimeout", "RemoteProtocolError", "ConnectError"}:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


# Chạy vòng lặp; lỗi tạm thời được thử lại tối đa `retries` lần, chờ 2-5 giây (hoặc
# 10-20 giây nếu bị giới hạn 429).
async def run_tool_loop(model_factory, loop: ToolLoop, context, retries=2) -> None:
    """model_factory returns a fresh MAF chat client (app/core/llm/maf_clients.py) per call.

    A transient provider error before anything was accepted is retried `retries` times with
    a fresh client. Tool state and budgets carry over, so a retry cannot exceed them.
    """
    if loop.max_llm_calls < 1:
        raise ValueError("max_llm_calls must be positive")
    for attempt in range(retries + 1):
        try:
            await _run_maf(model_factory, loop, context)
            return
        except Exception as exc:
            if loop.is_done() or attempt == retries or not is_transient(exc):
                raise
            logger.warning(
                "tool_loop request_id=%s agent=%s outcome=retry error_type=%s",
                context.request_id, loop.name, type(exc).__name__,
            )
            delays = RATE_LIMIT_DELAYS_S if is_rate_limited(exc) else RETRY_DELAYS_S
            await asyncio.sleep(delays[min(attempt, len(delays) - 1)])


# Chạy bằng Microsoft Agent Framework. MAF mặc định không có ba đảm bảo trên, nên cần hai middleware bên
# dưới.
async def _run_maf(client_factory, loop, context):
    """MAF defaults lack the three guarantees; the middleware below adds them.

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

    # Đếm số lần gọi model; vượt giới hạn thì dừng bằng AgentError.
    class ModelCallBudget(ChatMiddleware):
        def __init__(self):
            self.calls = 0

        async def process(self, chat_context, call_next):
            self.calls += 1
            if self.calls > loop.max_llm_calls:
                raise AgentError(loop.budget_message)
            await call_next()

    # Công cụ báo AgentError thì dừng cả vòng lặp (MAF mặc định gửi lỗi lại cho model và chạy tiếp); bài nộp
    # được chấp nhận thì kết thúc ngay.
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

    # Mỗi lần chạy một client mới, để giới hạn và middleware không lẫn giữa các yêu cầu chạy song song.
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
    # Lấy lại AgentError gốc bên trong lỗi middleware của MAF.
    except MiddlewareFailure as exc:
        if loop.is_done():
            return
        cause = exc.__cause__
        raise (cause if isinstance(cause, AgentError) else AgentError(str(exc))) from None
    except AgentError:
        if loop.is_done():
            return
        raise
