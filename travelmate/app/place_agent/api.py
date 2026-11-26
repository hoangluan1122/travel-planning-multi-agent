"""Run only Place Agent: uvicorn app.place_agent.api:create_app --factory."""

# API chỉ chạy Place Agent (bản thử nghiệm đầu). Ứng dụng phụ, chạy riêng; trang web chính không dùng file
# này.

import secrets
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.base import AgentError
from app.core.models import Context
from app.place_agent.agent import PlaceAgentInput, PlaceAgentOutput, PlaceAssistant
from app.tools.places.osm_places import OSMPlaceProvider
from app.tools.places.providers import LiveProvider


class PlaceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    google_api_key: SecretStr = SecretStr("")
    google_maps_api_key: SecretStr = SecretStr("")
    travelmate_api_token: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    travelmate_agent_timeout: float = Field(default=60, gt=0, le=180)
    place_provider: Literal["osm", "google", "browser"] = "osm"
    overpass_url: str = "https://overpass-api.de/api/interpreter"


def create_app(settings=None, assistant=None):
    settings = settings or PlaceSettings()
    token = settings.travelmate_api_token.get_secret_value()
    if not token:
        raise ValueError("Place Agent requires TRAVELMATE_API_TOKEN")
    if assistant is None and not settings.google_api_key.get_secret_value():
        raise ValueError("Place Agent requires GOOGLE_API_KEY")
    if (
        assistant is None
        and settings.place_provider == "google"
        and not settings.google_maps_api_key.get_secret_value()
    ):
        raise ValueError("Google provider requires GOOGLE_MAPS_API_KEY")
    provider = (
        OSMPlaceProvider(settings.overpass_url)
        if settings.place_provider == "osm"
        else (
            LiveProvider(settings.google_maps_api_key.get_secret_value())
            if settings.place_provider == "google"
            else None
        )
    )

    app = FastAPI(title="TravelMate — Standalone Place Agent")
    bearer = HTTPBearer(auto_error=False)

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(401, "Invalid API token")

    @app.get("/health")
    async def health():
        return {"status": "ok", "component": "place_agent", "providers_verified": False}

    @app.post("/api/v1/agent/places", response_model=PlaceAgentOutput, dependencies=[Depends(authorize)])
    async def discover(data: PlaceAgentInput):
        try:
            if assistant is not None:
                return await assistant.run(data, Context(), timeout=settings.travelmate_agent_timeout)
            from app.core.llm.maf_clients import maf_gemini_client_factory

            async with maf_gemini_client_factory(
                settings.google_api_key.get_secret_value(), settings.gemini_model
            ) as factory:
                return await PlaceAssistant(factory, provider).run(
                    data, Context(), timeout=settings.travelmate_agent_timeout
                )
        except TimeoutError:
            raise HTTPException(504, "Place agent timed out") from None
        except AgentError:
            raise HTTPException(502, "Place agent could not produce validated output") from None
        except Exception:
            raise HTTPException(
                502, "Place agent failed; check configuration and provider availability"
            ) from None

    return app
