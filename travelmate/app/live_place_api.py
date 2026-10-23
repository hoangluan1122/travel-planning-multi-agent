"""Local runnable application for one live Place Agent, without the demo workflow."""

import asyncio
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .geo_places import GeoPlaceService
from .live_place_agent import LivePlaceAgent, LivePlaceReport, LivePlaceRequest
from .models import Context
from .vietnam_regions import load_catalog

UI = Path(__file__).resolve().parent.parent / "frontend" / "place-agent-live"


class LivePlaceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    live_place_mode: Literal["tool_workflow", "adk_llm"] = "tool_workflow"
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    travelmate_api_token: SecretStr = SecretStr("")


def create_app(settings=None, agent=None):
    settings = settings or LivePlaceSettings()
    if (
        settings.live_place_mode == "adk_llm"
        and not settings.google_api_key.get_secret_value()
        and agent is None
    ):
        raise ValueError("ADK mode requires GOOGLE_API_KEY; never silently switch engines")
    app = FastAPI(title="TravelMate — Live Place Agent", version="1.0.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    bearer = HTTPBearer(auto_error=False)
    slots = asyncio.Semaphore(1)
    last_success = None
    geo_service = GeoPlaceService()

    async def authorize(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        # Standalone local application, same-origin UI. No cross-origin POSTs.
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin requests are not supported")
        token = settings.travelmate_api_token.get_secret_value()
        if token and (credentials is None or not secrets.compare_digest(credentials.credentials, token)):
            raise HTTPException(401, "Invalid API token", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "mode": settings.live_place_mode,
            "data_source": "live_web",
            "token_required": bool(settings.travelmate_api_token.get_secret_value()),
            "last_success_at": last_success,
            "supported_categories": ["hotel", "restaurant", "attraction"],
            "providers": ["GeoNames/Open-Meteo", "Photon/OpenStreetMap"],
            "coverage": {"current_reference_regions": 34, "historical_reference_regions": 63, "poi_exhaustive": False},
        }

    @app.get("/api/v1/places/regions")
    async def regions():
        catalog = load_catalog()
        return {"regions": [geo_service.region_location(r) for r in catalog.regions.values()],
                "warning": "Ranh giới tham chiếu có phiên bản, không phải xác nhận pháp lý hiện hành. Dữ liệu POI lấy trực tiếp khi tìm."}

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(UI / "index.html")

    @app.get("/app.js", include_in_schema=False)
    async def javascript():
        return FileResponse(UI / "app.js", media_type="text/javascript")

    @app.post("/api/v1/places/live", response_model=LivePlaceReport, dependencies=[Depends(authorize)])
    async def search(data: LivePlaceRequest, response: Response):
        nonlocal last_success
        if slots.locked():
            raise HTTPException(
                429, "Agent đang xử lý một yêu cầu khác. Vui lòng chờ.", headers={"Retry-After": "10"}
            )
        context = Context()
        response.headers["X-Request-ID"] = str(context.request_id)
        async with slots:
            try:
                if agent is not None:
                    result = await agent.run(data, context, 140)
                elif settings.live_place_mode == "adk_llm":
                    from .specialist_api import gemini_factory

                    async with gemini_factory(settings) as factory:
                        result = await LivePlaceAgent(model_factory=factory, geo_service=geo_service).run(
                            data, context, 140
                        )
                else:
                    result = await LivePlaceAgent(geo_service=geo_service).run(data, context, 140)
            except TimeoutError:
                raise HTTPException(504, "Hết thời gian chạy agent; chưa có kết quả được xác nhận.") from None
        if result.status in {"success", "partial"}:
            last_success = result.completed_at.isoformat()
        elif result.status not in {"needs_location", "no_results"}:
            response.status_code = (
                504 if result.status == "timeout" else 503 if result.status == "blocked" else 502
            )
        return result

    return app
