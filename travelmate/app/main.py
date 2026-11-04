import secrets
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, Field, field_validator
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
from .telemetry import configure_telemetry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    travelmate_mode: Literal["demo", "live"] = "demo"
    travelmate_api_token: str = ""
    travelmate_agent_timeout: float = 45
    google_api_key: str = ""
    google_maps_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    agent_engine: Literal["adk", "maf"] = Field(
        default="adk", validation_alias=AliasChoices("agent_engine", "planner_engine")
    )
    # classic: asyncio pipeline in app/orchestrator.py; workflow: MAF Workflow graph (needs --extra maf)
    travelmate_orchestrator: Literal["classic", "workflow"] = "classic"
    # Live place/weather source: google (Places API, needs GOOGLE_MAPS_API_KEY) or
    # open_data (OpenStreetMap/Photon + Open-Meteo, no key)
    travelmate_place_provider: Literal["google", "open_data"] = "google"
    # Saved preferences for planning (read-only). The host binds one authenticated identity;
    # requests cannot choose whose memory is read. Unset = request interests only.
    travelmate_memory_user: UUID | None = None
    travelmate_memory_db: Path = Path("agent-memory.sqlite3")
    # OpenTelemetry traces: off, console, or otlp (OTEL_EXPORTER_OTLP_ENDPOINT); needs --extra maf
    travelmate_telemetry: Literal["off", "console", "otlp"] = "off"

    @field_validator("travelmate_memory_user", mode="before")
    @classmethod
    def blank_memory_user_is_unset(cls, value):
        # .env.example ships TRAVELMATE_MEMORY_USER= empty; that means "not configured".
        return None if isinstance(value, str) and not value.strip() else value


def memory_store(settings):
    if settings.travelmate_memory_user is None:
        return None
    from .specialists.memory import MemorySpecialist

    return MemorySpecialist(settings.travelmate_memory_db, settings.travelmate_memory_user)


def live_planner(settings):
    if settings.agent_engine == "maf":
        from .maf_adapter import MafPlanner
        from .maf_clients import maf_gemini_client

        return MafPlanner(lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model))
    return AdkPlanner(settings.gemini_model)


def create_app(settings=None, orchestrator=None, provider=None):
    settings = settings or Settings()
    configure_telemetry(settings.travelmate_telemetry, "travelmate-api")
    if settings.travelmate_mode == "live":
        if not settings.google_api_key or not settings.travelmate_api_token:
            raise ValueError("Live mode requires GOOGLE_API_KEY and TRAVELMATE_API_TOKEN")
        if settings.travelmate_place_provider == "google" and not settings.google_maps_api_key:
            raise ValueError("TRAVELMATE_PLACE_PROVIDER=google requires GOOGLE_MAPS_API_KEY")
        # ADK reads the key from the environment; dotenv does not export it automatically.
        import os

        os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    if provider is None:
        if settings.travelmate_mode == "demo":
            provider = DemoProvider()
        elif settings.travelmate_place_provider == "open_data":
            from .open_data_provider import OpenDataProvider

            provider = OpenDataProvider()
        else:
            provider = LiveProvider(settings.google_maps_api_key)
    if orchestrator is None:
        registry = Registry()
        for agent in [
            MemoryAgent(memory_store(settings)),
            PlaceAgent(provider),
            WeatherAgent(provider),
            RecommendationAgent(),
            PlannerAgent(live_planner(settings) if settings.travelmate_mode == "live" else None),
            BudgetAgent(),
        ]:
            registry.register(agent)
        if settings.travelmate_orchestrator == "workflow":
            try:
                import agent_framework  # noqa: F401
            except ImportError:
                raise ValueError("TRAVELMATE_ORCHESTRATOR=workflow requires the maf extra") from None
            from .workflow_orchestrator import WorkflowOrchestrator

            orchestrator_cls = WorkflowOrchestrator
        else:
            orchestrator_cls = Orchestrator
        orchestrator = orchestrator_cls(registry, settings.travelmate_mode, settings.travelmate_agent_timeout)
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
        return {
            "status": "ok",
            "mode": settings.travelmate_mode,
            "token_required": bool(settings.travelmate_api_token),
            "place_provider": None if settings.travelmate_mode == "demo" else settings.travelmate_place_provider,
            "agent_engine": settings.agent_engine,
            "orchestrator": settings.travelmate_orchestrator,
        }

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

    @app.middleware("http")
    async def revalidate_ui(request, call_next):
        # Make browsers revalidate UI files (ETag) so a restarted server never runs stale JS.
        response = await call_next(request)
        if request.url.path.startswith("/ui/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend"), name="ui")
    return app
