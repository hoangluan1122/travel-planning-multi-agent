"""Local-only harness for individual specialists; not a public identity boundary."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..models import Context, PlannerInput
from .budget import BudgetRequest, BudgetSpecialist
from .memory import MemoryRequest, MemorySpecialist
from .planner import PlannerSpecialist
from .recommendation import RecommendationRanker, RecommendationRequest, RecommendationSpecialist
from .routed_planner import RoutedPlannerInput, RoutedPlannerSpecialist
from .routing import RouteRequest, RouteSpecialist
from .trip_budget import TripBudgetRequest, TripBudgetSpecialist
from .weather import WeatherRequest, WeatherSpecialist


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"


async def run(args):
    raw = args.input.read_text(encoding="utf-8-sig")
    client = None
    try:
        if args.agent in {"recommendation", "planner", "routed-planner"}:
            from google.adk.models import Gemini
            from google.genai import Client

            settings = Settings()
            if not settings.google_api_key.get_secret_value():
                raise ValueError("Configure GOOGLE_API_KEY in .env locally")
            client = Client(api_key=settings.google_api_key.get_secret_value())

            class RequestGemini(Gemini):
                @property
                def api_client(self):
                    return client

            def factory():
                return RequestGemini(model=settings.gemini_model)

            agent, schema = (
                (RecommendationSpecialist(factory), RecommendationRequest)
                if args.agent == "recommendation"
                else (PlannerSpecialist(factory), PlannerInput)
            )
            if args.agent == "routed-planner":
                agent, schema = RoutedPlannerSpecialist(factory), RoutedPlannerInput
        elif args.agent == "budget":
            agent, schema = BudgetSpecialist(), BudgetRequest
        elif args.agent == "trip-budget":
            agent, schema = TripBudgetSpecialist(), TripBudgetRequest
        elif args.agent == "recommendation-score":
            agent, schema = RecommendationRanker(), RecommendationRequest
        elif args.agent == "weather":
            agent, schema = WeatherSpecialist(), WeatherRequest
        elif args.agent == "route":
            agent, schema = RouteSpecialist(), RouteRequest
        else:
            if args.user is None:
                raise ValueError("Memory requires --user UUID for the local test identity")
            agent, schema = MemorySpecialist(args.memory_db, args.user), MemoryRequest
        result = await agent.run(schema.model_validate_json(raw), Context(), timeout=60)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(result.model_dump_json(indent=2))
    finally:
        if client is not None:
            try:
                await client.aio.aclose()
            finally:
                client.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "agent",
        choices=[
            "weather",
            "budget",
            "trip-budget",
            "memory",
            "recommendation",
            "recommendation-score",
            "planner",
            "route",
            "routed-planner",
        ],
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--user", type=UUID)
    parser.add_argument("--memory-db", type=Path, default=Path("agent-memory.sqlite3"))
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        # Exception bodies may contain provider URLs, prompts or credentials.
        parser.exit(1, f"Agent failed ({type(exc).__name__}). Check input schema/configuration.\n")


if __name__ == "__main__":
    main()
