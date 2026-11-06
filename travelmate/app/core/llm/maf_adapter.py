"""Microsoft Agent Framework engine for the planner.

Same tools, instruction and submit gate as AdkPlanner; app/core/llm/tool_loop.py restores the
ADK guarantees (fail-closed budgets, exact model-call limit, stop on acceptance).
"""

from app.core.llm.adk_adapter import _Planner


class MafPlanner(_Planner):
    """client_factory returns a fresh chat client per call so iteration limits and
    middleware set by the loop never leak between concurrent requests."""

    engine = "maf"
