"""Local-only harness for individual specialists; not a public identity boundary."""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr
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
    agent_engine: Literal["adk", "maf"] = Field(
        default="adk", validation_alias=AliasChoices("agent_engine", "planner_engine")
    )


def write_result(args, result):
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2))


async def run(args):
    raw = args.input.read_text(encoding="utf-8-sig")
    settings = Settings()
    if args.agent in {"recommendation", "planner", "routed-planner"}:
        from ..adk_adapter import AdkPlanner
        from ..maf_adapter import MafPlanner
        from ..specialist_api import agent_model_factory

        if not settings.google_api_key.get_secret_value():
            raise ValueError("Configure GOOGLE_API_KEY in .env locally")
        engine = settings.agent_engine
        planner_cls = MafPlanner if engine == "maf" else AdkPlanner
        async with agent_model_factory(settings, engine) as factory:
            if args.agent == "recommendation":
                agent, schema = RecommendationSpecialist(factory, engine=engine), RecommendationRequest
            elif args.agent == "routed-planner":
                agent, schema = RoutedPlannerSpecialist(factory, planner_cls=planner_cls), RoutedPlannerInput
            else:
                agent, schema = PlannerSpecialist(factory, planner_cls), PlannerInput
            result = await agent.run(schema.model_validate_json(raw), Context(), timeout=60)
        write_result(args, result)
        return
    if args.agent == "budget":
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
    write_result(args, result)



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
