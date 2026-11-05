"""OpenTelemetry traces for TravelMate agents (opt-in).

Every BaseAgent.run opens an "agent <name>" span, for both engines and for the
deterministic agents. With TRAVELMATE_TELEMETRY=console|otlp the MAF providers are
configured, so MAF's own spans (invoke_agent, chat, execute_tool) nest under ours and
one request becomes one trace.

Spans carry agent name, request_id and outcome only. Prompt and message content is
never exported: sensitive telemetry stays disabled.
"""

import logging
from contextlib import contextmanager, nullcontext
from typing import Literal

logger = logging.getLogger(__name__)

TelemetryMode = Literal["off", "console", "otlp"]
_configured = False

try:
    from opentelemetry import trace as _trace
except ImportError:  # base install without the ai/maf extras
    _trace = None


def configure_telemetry(mode: TelemetryMode, service_name: str = "travelmate") -> None:
    """Call once at startup. otlp reads OTEL_EXPORTER_OTLP_ENDPOINT and related env vars."""
    global _configured
    if mode == "off" or _configured:
        return
    try:
        from agent_framework.observability import configure_otel_providers
    except ImportError:
        raise ValueError("TRAVELMATE_TELEMETRY requires the maf dependency extra") from None
    configure_otel_providers(
        service_name=service_name,
        enable_console_exporters=mode == "console",
        enable_sensitive_data=False,
        enable_message_events=False,
    )
    _configured = True
    logger.info("telemetry mode=%s service=%s", mode, service_name)


@contextmanager
def agent_span(agent_name: str, request_id):
    """Span around one agent invocation; a no-op when OpenTelemetry is not installed."""
    if _trace is None:
        with nullcontext() as span:
            yield span
        return
    tracer = _trace.get_tracer("travelmate")
    with tracer.start_as_current_span(
        f"agent {agent_name}",
        attributes={"travelmate.agent": agent_name, "travelmate.request_id": str(request_id)},
        record_exception=False,  # exception messages may hold provider details
        set_status_on_exception=False,
    ) as span:
        yield span


def set_outcome(span, outcome: str) -> None:
    if span is None or _trace is None:
        return
    span.set_attribute("travelmate.outcome", outcome)
    if outcome != "success":
        span.set_status(_trace.Status(_trace.StatusCode.ERROR, outcome))
