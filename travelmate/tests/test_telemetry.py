"""One request = one trace: agent spans with MAF spans nested inside, no prompt content."""

import json

import pytest

pytest.importorskip("agent_framework")
pytest.importorskip("opentelemetry.sdk")
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_adk_tools import fixture_data
from test_maf_tools import ScriptedClient
from test_planning import payload

import app.core.telemetry as telemetry
from app.core.base import AgentError
from app.core.llm.maf_adapter import MafPlanner
from app.core.models import Context, TripRequest
from app.memory.preferences import MemoryAgent
from app.specialists.planner import PlannerSpecialist


@pytest.fixture(scope="module")
def exporter():
    from agent_framework.observability import enable_instrumentation

    memory = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(memory))
    enable_instrumentation(enable_sensitive_data=False)
    return memory


@pytest.fixture
def spans(exporter):
    exporter.clear()
    yield exporter
    exporter.clear()


def by_name(finished, prefix):
    return [s for s in finished if s.name.startswith(prefix)]


@pytest.mark.asyncio
async def test_every_agent_run_has_a_span_with_outcome(spans):
    context = Context()
    await MemoryAgent().run(TripRequest(**payload()), context)
    (span,) = by_name(spans.get_finished_spans(), "agent memory")
    assert span.attributes["travelmate.agent"] == "memory"
    assert span.attributes["travelmate.request_id"] == str(context.request_id)
    assert span.attributes["travelmate.outcome"] == "success"
    assert span.status.status_code == trace.StatusCode.UNSET


@pytest.mark.asyncio
async def test_failed_agent_span_is_error_without_exception_text(spans):
    data, _ = await fixture_data()
    with pytest.raises(AgentError):
        await PlannerSpecialist(lambda: ScriptedClient([]), MafPlanner).run(data, Context())
    (span,) = by_name(spans.get_finished_spans(), "agent planner_specialist")
    assert span.attributes["travelmate.outcome"] == "failed"
    assert span.status.status_code == trace.StatusCode.ERROR
    assert not span.events  # exception message is not recorded


@pytest.mark.asyncio
async def test_maf_spans_nest_under_agent_span_and_hold_no_prompt_content(spans):
    data, draft = await fixture_data()
    marker = "SECRET-NOTE-7f3a"
    data.trip.notes = marker
    client = ScriptedClient(
        [
            {"name": "inspect_trip", "args": {}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
        ]
    )
    await PlannerSpecialist(lambda: client, MafPlanner).run(data, Context())

    finished = spans.get_finished_spans()
    (root,) = by_name(finished, "agent planner_specialist")
    maf = [s for s in finished if s is not root and s.context.trace_id == root.context.trace_id]
    assert maf, "MAF emitted no spans in the agent's trace"
    names = {s.name.split(" ")[0] for s in maf}
    assert "execute_tool" in names
    assert all(s.parent is not None for s in maf)

    exported = json.dumps(
        [dict(s.attributes) for s in finished] + [dict(e.attributes) for s in finished for e in s.events],
        default=str,
    )
    # Tool definitions (names, docstrings) are exported as gen_ai.tool.definitions; that is
    # schema, not user data. User data, tool arguments and tool results must not be.
    assert marker not in exported  # trip notes, returned by inspect_trip
    assert "demo-attraction" not in exported  # place id in submit_itinerary arguments
    assert "Da Nang" not in exported  # destination in tool result


def test_configure_telemetry_is_opt_in_and_never_sensitive(monkeypatch):
    import agent_framework.observability as observability

    calls = []
    monkeypatch.setattr(observability, "configure_otel_providers", lambda **kw: calls.append(kw))
    monkeypatch.setattr(telemetry, "_configured", False)

    telemetry.configure_telemetry("off")
    assert calls == []

    telemetry.configure_telemetry("console", "svc")
    telemetry.configure_telemetry("console", "svc")  # only once per process
    assert len(calls) == 1
    assert calls[0]["service_name"] == "svc"
    assert calls[0]["enable_console_exporters"] is True
    assert calls[0]["enable_sensitive_data"] is False
    assert calls[0]["enable_message_events"] is False
