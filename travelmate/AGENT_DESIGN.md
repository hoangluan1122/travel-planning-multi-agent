# Agent implementation notes

## Sources examined

- ReAct paper: https://arxiv.org/abs/2210.03629 — motivates alternating actions and observations rather than trusting a single generated answer.
- Microsoft AutoGen implementation: https://github.com/microsoft/autogen/blob/main/python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py — bounded tool iterations, tool results and request-state concerns. TravelMate does not depend on AutoGen or copy its implementation.
- Google ADK function tools: https://adk.dev/tools-custom/function-tools/ — Python function signatures and docstrings define callable tools.
- Installed Google ADK 1.39.1 source: models/base_llm.py, agents/run_config.py, agents/invocation_context.py and runners.py. Used to verify model injection, call limits and cleanup against the actual installed version.

## Implemented execution

The orchestrator fetches Places and weather before invoking Planner. Planner uses an ADK LlmAgent, not a manually parsed single prompt response. Its inspect_trip tool exposes the request-scoped evidence. The model then calls submit_itinerary; Pydantic and domain checks reject unknown place IDs, missing/duplicate/out-of-order dates and overlapping activities. Validation errors are returned as tool observations so the model can repair its proposal.

Only the validated Python object is returned to the API. Free-form model text is never accepted as a plan. Limits are eight model calls, three evidence reads and three submissions per invocation, plus the existing agent timeout. Each request owns its tools, accepted result and in-memory ADK session; cleanup closes the runner and deletes the session. Logs record request ID, tool name and acceptance only, not prompts, keys or private reasoning.

This is an application of tool-use patterns, not a reproduction of the ReAct research benchmark. Prompt instructions mitigate but do not eliminate prompt injection; schema and ID validation provide enforceable boundaries on the returned draft. Tools cannot book, pay, execute shell commands or write user data.

## What is and is not an LLM agent

| Component | Current implementation |
| --- | --- |
| Planner | Gemini via ADK in live mode; evidence-reading and validated submission tools |
| Place | Deterministic Google Places HTTP adapter; sightseeing candidates only |
| Weather | Deterministic Open-Meteo adapter; missing forecast reported |
| Budget | Decimal arithmetic; unknown costs remain unknown |
| Recommendation | Keyword ranking, not an LLM recommender |
| Memory | Request preferences only; no durable user memory yet |

Calling every component an agent does not mean it needs an LLM. Financial addition and response validation should remain deterministic. A2A transport, authenticated persistent memory, hotel/restaurant retrieval, route feasibility and durable execution logs remain future implementation work.

## Verification boundary

Tests inject a scripted BaseLlm into the real ADK Runner. ADK executes the real Python tools; no billed model is called. Tests cover correction of invented places, rejection of text-only output, evidence-read requirement, submission/model limits and concurrent request isolation. These tests verify control flow, not Gemini planning quality. A live evaluation still requires locally configured keys and a small approved API budget. Never send keys in chat.

Suggested live checks: a one-day trip, a three-day trip, a destination with an ambiguous name, dates outside the forecast window, a deliberately tiny budget and adversarial text in interests. Record model/version, tool counts, latency, validation outcome and missing-data warnings; do not treat a fluent answer as evidence of correctness.
