import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic_settings import BaseSettings, SettingsConfigDict

from .adk_adapter import AdkPlanner
from .agents import (
    AgentError,
    BudgetAgent,
    MemoryAgent,
    PlaceAgent,
    PlannerAgent,
    RecommendationAgent,
    Registry,
    WeatherAgent,
)
from .models import PlaceResult, PlaceSearchRequest, PlanResponse, TripRequest
from .orchestrator import Orchestrator
from .providers import DemoProvider, LiveProvider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    travelmate_mode: Literal["demo", "live"] = "demo"
    travelmate_api_token: str = ""
    travelmate_agent_timeout: float = 45
    google_api_key: str = ""
    google_maps_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"


def create_app(settings=None, orchestrator=None, provider=None):
    settings = settings or Settings()
    if settings.travelmate_mode == "live":
        if not all([settings.google_api_key, settings.google_maps_api_key, settings.travelmate_api_token]):
            raise ValueError("Live mode requires Gemini key, Maps key and an API token")
        # ADK reads the key from the environment; dotenv does not export it automatically.
        import os

        os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    if provider is None:
        provider = (
            DemoProvider()
            if settings.travelmate_mode == "demo"
            else LiveProvider(settings.google_maps_api_key)
        )
    if orchestrator is None:
        registry = Registry()
        for agent in [
            MemoryAgent(),
            PlaceAgent(provider),
            WeatherAgent(provider),
            RecommendationAgent(),
            PlannerAgent(AdkPlanner(settings.gemini_model) if settings.travelmate_mode == "live" else None),
            BudgetAgent(),
        ]:
            registry.register(agent)
        orchestrator = Orchestrator(registry, settings.travelmate_mode, settings.travelmate_agent_timeout)
    app = FastAPI(title="TravelMate API", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if settings.travelmate_api_token and (
            credentials is None
            or not secrets.compare_digest(credentials.credentials, settings.travelmate_api_token)
        ):
            raise HTTPException(401, "Invalid API token")

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": settings.travelmate_mode,
                "token_required": bool(settings.travelmate_api_token)}

    @app.post("/api/v1/places/search", response_model=PlaceResult, dependencies=[Depends(authorize)])
    async def search_places(query: PlaceSearchRequest):
        try:
            return await provider.search_places(query)
        except TimeoutError:
            raise HTTPException(504, "Place lookup timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception:
            raise HTTPException(502, "Place lookup failed") from None

    @app.post("/api/v1/plans/preview", response_model=PlanResponse, dependencies=[Depends(authorize)])
    async def preview(trip: TripRequest):
        try:
            return await orchestrator.plan(trip)
        except TimeoutError:
            raise HTTPException(504, "Agent processing timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception:
            # Never expose provider URLs containing keys, prompts or stack traces.
            raise HTTPException(502, "Planning failed; check provider configuration and retry") from None

    @app.get("/", include_in_schema=False)
    async def frontend():
        return RedirectResponse("/ui/travelmate-v2/index.html")

    app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend"), name="ui")
    return app
