"""TravelMate tools as an MCP server (course lesson 11: Model Context Protocol).

Any MCP client (Claude Desktop, Claude Code, VS Code, MAF's MCPStdioTool…) can call:

- search_places    places from OpenStreetMap/Photon (or Google, per settings) with cited ticket fees
- weather_forecast daily forecast from Open-Meteo
- ask_guide        the Agentic RAG guide: answers with cited Wikipedia/Wikivoyage/ticket sources
- plan_trip        the full multi-agent planner (Planning pattern + Metacognition)

and read the resource travelmate://tickets (the cited ticket table).

Run over stdio (what desktop clients launch):   uv run python -m app.protocols.mcp_server
or Streamable HTTP on localhost:                uv run python -m app.protocols.mcp_server --http --port 8765

The server reads the same .env as the API. Tool errors return a short message, never
provider URLs, keys or stack traces. Over stdio nothing but MCP messages goes to stdout.
"""

import argparse
import asyncio
import json
import logging
import secrets
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field, ValidationError

from app.agents.concierge import weather_label
from app.core.base import AgentError
from app.core.models import Context, PlaceSearchRequest, TripRequest
from app.protocols.summaries import place_summary, plan_summary
from app.tools.prices.ticket_prices import TABLE, apply_tickets

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "TravelMate plans trips in Vietnam from free, cited sources. Use search_places for concrete places, "
    "weather_forecast for the next ~14 days, ask_guide for facts about a sight or city (it cites sources and "
    "never invents fees or hours), and plan_trip for a day-by-day itinerary (takes 30-120 seconds). "
    "Prices not in the sources are reported as unknown, never as zero."
)


def safe(error):
    """A message for the client that never carries provider URLs, keys or tracebacks."""
    if isinstance(error, ValidationError):
        return "Invalid input: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
    if isinstance(error, TimeoutError):
        return "The data source timed out; retry shortly."
    if isinstance(error, AgentError):
        return str(error)[:300]
    return "The request failed; retry shortly."


def create_mcp(services, name="TravelMate"):
    mcp = FastMCP(name, instructions=INSTRUCTIONS)
    provider, orchestrator, settings = services.provider, services.orchestrator, services.settings
    guide = services.chat.guide

    async def guarded(label, work):
        try:
            async with asyncio.timeout(settings.travelmate_agent_timeout + 30):
                return await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("mcp tool=%s outcome=failed error_type=%s", label, type(exc).__name__)
            raise ValueError(safe(exc)) from None

    @mcp.tool()
    async def search_places(
        destination: Annotated[str, Field(description="City or area in Vietnam, e.g. 'Huế' or 'Hội An'")],
        category: Annotated[Literal["attraction", "restaurant", "hotel"], Field(description="Kind of place")] = (
            "attraction"),
        keyword: Annotated[str, Field(description="Optional literal keyword, e.g. 'vegetarian', 'tomb'")] = "",
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> dict:
        """Find real places (sights, restaurants or stays) near a destination, with cited ticket fees where known."""

        async def work():
            # Sights such as Huế's royal tombs lie well outside the centre; food and stays stay close.
            radius = 10000 if category == "attraction" else 5000
            query = PlaceSearchRequest(destination=destination, category=category, keyword=keyword, limit=limit,
                                       radius_m=radius)
            result = await provider.search_places(query)
            places = apply_tickets(result.places, destination)
            return {"places": [place_summary(p) for p in places], "warnings": result.warnings}

        return await guarded("search_places", work())

    @mcp.tool()
    async def weather_forecast(
        destination: Annotated[str, Field(description="City or area in Vietnam")],
        start_date: Annotated[date | None, Field(description="First day (YYYY-MM-DD); default today")] = None,
        end_date: Annotated[date | None, Field(description="Last day (YYYY-MM-DD); default start + 2 days")] = None,
    ) -> dict:
        """Daily weather forecast (Open-Meteo) for a destination; only the next ~14 days are available."""

        async def work():
            start = start_date or date.today()
            trip = TripRequest(destination=destination, start_date=start, end_date=end_date or start + timedelta(2),
                               travelers=1, budget_vnd=Decimal(1))
            forecast = await provider.forecast(trip)
            return {
                "days": [{"date": d.date.isoformat(), "weather_code": d.weather_code,
                          "summary": weather_label(d.weather_code)} for d in forecast.days],
                "warnings": forecast.warnings,
                "source": "Open-Meteo",
            }

        return await guarded("weather_forecast", work())

    @mcp.tool()
    async def ask_guide(
        question: Annotated[str, Field(min_length=3, max_length=300, description="Question about a sight or city")],
        destination: Annotated[str | None, Field(description="Optional trip destination for context")] = None,
    ) -> dict:
        """Answer a travel question from Wikipedia, Wikivoyage and the cited ticket table, with citations.

        Numbers (fees, years, hours) in the answer always appear in a cited source; missing facts are
        reported as missing (status partial or not_found).
        """

        async def work():
            answer = await guide.ask(question, Context(), destination)
            return answer.model_dump(mode="json")

        return await guarded("ask_guide", work())

    @mcp.tool()
    async def plan_trip(
        destination: Annotated[str, Field(description="City or area in Vietnam")],
        start_date: Annotated[date, Field(description="First day, YYYY-MM-DD, not in the past")],
        end_date: Annotated[date, Field(description="Last day, YYYY-MM-DD, at most 13 days after start")],
        travelers: Annotated[int, Field(ge=1, le=50)],
        budget_vnd: Annotated[int, Field(gt=0, description="Total budget in VND, e.g. 5000000")],
        interests: Annotated[list[str], Field(max_length=10, description="e.g. ['lăng tẩm', 'ăn chay']")] = [],  # noqa: B006
        notes: Annotated[str, Field(max_length=500, description="Free-text wishes")] = "",
    ) -> dict:
        """Plan a day-by-day itinerary with the multi-agent planner (30-120 s). Returns days, costs and checks."""

        async def work():
            trip = TripRequest(destination=destination, start_date=start_date, end_date=end_date,
                               travelers=travelers, budget_vnd=Decimal(budget_vnd), interests=interests, notes=notes)
            plan = await orchestrator.plan(trip)
            return plan_summary(plan)

        return await guarded("plan_trip", work())

    @mcp.resource("travelmate://tickets", mime_type="application/json")
    def tickets() -> str:
        """Hand-checked entrance fees for well-known sights in Huế and Hội An, with source URLs."""
        return json.dumps(json.loads(TABLE.read_text("utf-8")), ensure_ascii=False)

    return mcp


class BearerGuard:
    """ASGI wrapper: every HTTP request needs Authorization: Bearer <token> (constant-time check)."""

    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode("latin-1")
            if not (auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], self.token)):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"error":"Invalid API token"}'})
                return
        await self.app(scope, receive, send)


def http_app(mcp, token):
    """Streamable HTTP app; protected by the API token whenever one is configured."""
    app = mcp.streamable_http_app()
    return BearerGuard(app, token) if token else app


def main(argv=None):
    parser = argparse.ArgumentParser(description="TravelMate MCP server")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    from app.main import Settings, build_services

    settings = Settings()
    if not args.http:
        settings.travelmate_telemetry = "off"  # a console exporter would corrupt the stdio stream
    logging.basicConfig(level=logging.WARNING)  # stderr
    mcp = create_mcp(build_services(settings))
    if args.http:
        import uvicorn

        if not settings.travelmate_api_token:
            logging.getLogger(__name__).warning("MCP over HTTP without TRAVELMATE_API_TOKEN: anyone on this machine "
                                                "can call it")
        uvicorn.run(http_app(mcp, settings.travelmate_api_token), host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
