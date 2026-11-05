"""Transient model-provider errors get one retry; budget and other agent errors never do."""

import pytest

import app.tool_loop as tool_loop
from app.agents import AgentError
from app.models import Context
from app.tool_loop import ToolLoop, is_transient, run_tool_loop


class ServerError(Exception):  # same name as google.genai.errors.ServerError
    pass


class Wrapped(Exception):
    pass


def wrapped(inner):
    try:
        raise inner
    except Exception as exc:
        try:
            raise Wrapped("chat client failed") from exc
        except Wrapped as outer:
            return outer


def test_transient_detection_walks_the_cause_chain():
    assert is_transient(wrapped(ServerError("503")))
    status = Exception("rate limited")
    status.code = 429
    assert is_transient(wrapped(status))
    assert not is_transient(wrapped(AgentError("Planner submission budget exceeded")))
    assert not is_transient(ValueError("bad json"))


def loop(done):
    return ToolLoop(name="t", instruction="i", tools=[], message="m", max_llm_calls=2,
                    budget_message="b", is_done=lambda: done["v"])


@pytest.mark.asyncio
async def test_one_retry_after_a_transient_error(monkeypatch):
    calls, done = [], {"v": False}

    async def runner(factory, lp, ctx):
        calls.append(1)
        if len(calls) == 1:
            raise wrapped(ServerError("503"))
        done["v"] = True

    monkeypatch.setattr(tool_loop, "_run_maf", runner)
    monkeypatch.setattr(tool_loop, "RETRY_DELAYS_S", (0, 0))
    monkeypatch.setattr(tool_loop, "RATE_LIMIT_DELAYS_S", (0, 0))
    await run_tool_loop("maf", None, loop(done), Context())
    assert len(calls) == 2 and done["v"]


@pytest.mark.asyncio
async def test_no_retry_for_agent_errors_or_after_the_retry_budget(monkeypatch):
    calls = []

    async def budget(factory, lp, ctx):
        calls.append(1)
        raise AgentError("Planner model-call budget exceeded")

    monkeypatch.setattr(tool_loop, "_run_maf", budget)
    with pytest.raises(AgentError):
        await run_tool_loop("maf", None, loop({"v": False}), Context())
    assert len(calls) == 1

    async def always_down(factory, lp, ctx):
        calls.append(2)
        raise wrapped(ServerError("503"))

    monkeypatch.setattr(tool_loop, "_run_maf", always_down)
    monkeypatch.setattr(tool_loop, "RETRY_DELAYS_S", (0, 0))
    monkeypatch.setattr(tool_loop, "RATE_LIMIT_DELAYS_S", (0, 0))
    with pytest.raises(Wrapped):
        await run_tool_loop("maf", None, loop({"v": False}), Context())
    assert calls.count(2) == 3  # first try + 2 retries


def test_rate_limits_are_recognised_through_wrappers():
    status = Exception("quota")
    status.code = 429
    assert tool_loop.is_rate_limited(wrapped(status))
    assert not tool_loop.is_rate_limited(wrapped(ServerError("503")))
