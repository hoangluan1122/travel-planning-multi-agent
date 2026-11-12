import asyncio
import html
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agents.budget import BudgetAgent
from app.agents.concierge import ChatRequest, ChatResponse, ChatSession
from app.agents.itinerary import PlannerAgent
from app.agents.orchestrator import Orchestrator
from app.agents.place import PlaceAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.weather import WeatherAgent
from app.core.base import AgentError, Registry
from app.core.llm.adk_adapter import AdkPlanner
from app.core.models import PlaceResult, PlaceSearchRequest, PlanResponse, TripRequest
from app.core.telemetry import configure_telemetry
from app.memory.preferences import MemoryAgent
from app.memory.store import VIETNAM, StoreError
from app.tools.places.place_media import GooglePhotoProxy
from app.tools.places.providers import DemoProvider, LiveProvider
from app.trust.accounts import session_from

logger = logging.getLogger(__name__)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
INDEX = FRONTEND / "travelmate-v2" / "index.html"
# Pages anyone can read; search engines index these and nothing else.
PUBLIC_PAGES = {
    "home": ("TravelMate — Lên kế hoạch du lịch cùng AI",
             "Lập lịch trình du lịch Việt Nam theo từng ngày, ước tính chi phí so với ngân sách, xem thời tiết "
             "và hỏi Trợ lý AI."),
    "explore": ("Khám phá địa điểm — TravelMate", "Tìm điểm tham quan, quán ăn và khách sạn ở các điểm đến Việt Nam."),
    "chat": ("Trợ lý AI du lịch — TravelMate", "Hỏi quán ăn, giá vé, thời tiết hoặc nhờ lập lịch trình bằng tiếng Việt."),
    "create": ("Tạo chuyến đi — TravelMate", "Nhập điểm đến, ngày đi, số người và ngân sách để nhận lịch trình từng ngày."),
    "about": ("Giới thiệu — TravelMate", "TravelMate là gì, làm được gì và dữ liệu đến từ đâu."),
    "pricing": ("Bảng giá — TravelMate", "TravelMate miễn phí. Hạn mức sử dụng AI mỗi ngày và câu hỏi thường gặp."),
    "contact": ("Liên hệ — TravelMate", "Gửi câu hỏi, góp ý hoặc đề nghị hợp tác cho TravelMate."),
    "terms": ("Điều khoản sử dụng — TravelMate", "Điều khoản sử dụng dịch vụ TravelMate."),
    "privacy": ("Chính sách bảo mật — TravelMate", "TravelMate thu thập dữ liệu gì, dùng vào việc gì và quyền của bạn."),
}
QUOTA_LABELS = {"plan": "lượt lập lịch trình", "chat": "tin nhắn với Trợ lý AI"}


def seconds_to_midnight_vn():
    now = datetime.now(VIETNAM)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds()) + 1


def page_html(view, base):
    """index.html with the title, description, canonical link and share preview of one page."""
    text = INDEX.read_text("utf-8")
    page = PUBLIC_PAGES.get(view)
    if page is None:  # private or unknown pages: keep them out of search results
        return text.replace("<!--SEO-->", '<meta name="robots" content="noindex">')
    title, description = (html.escape(x) for x in page)
    url = html.escape(f"{base}/" + ("" if view == "home" else f"?view={view}"))
    image = html.escape(f"{base}/ui/travelmate-ui/assets/beach.jpg")
    seo = "\n".join([
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="website">', '<meta property="og:site_name" content="TravelMate">',
        '<meta property="og:locale" content="vi_VN">',
        f'<meta property="og:title" content="{title}">', f'<meta property="og:description" content="{description}">',
        f'<meta property="og:url" content="{url}">', f'<meta property="og:image" content="{image}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ])
    text = text.replace("<!--SEO-->", seo)
    start, end = text.index("<title>"), text.index("</title>") + len("</title>")
    text = text[:start] + f"<title>{title}</title>" + text[end:]
    start = text.index('<meta name="description" content="')
    end = text.index('">', start) + 2
    return text[:start] + f'<meta name="description" content="{description}">' + text[end:]

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
    # classic: asyncio pipeline in app/agents/orchestrator.py; workflow: MAF Workflow graph (needs --extra maf)
    # planning: Planning pattern (LLM decomposes the request into subtasks, re-plans on misses)
    travelmate_orchestrator: Literal["classic", "workflow", "planning"] = "classic"
    # Live place/weather source: google (Places API, needs GOOGLE_MAPS_API_KEY) or
    # open_data (OpenStreetMap/Photon + Open-Meteo, no key)
    travelmate_place_provider: Literal["google", "open_data"] = "google"
    # Saved preferences for planning (read-only). The host binds one authenticated identity;
    # requests cannot choose whose memory is read. Unset = request interests only.
    travelmate_memory_user: UUID | None = None
    travelmate_memory_db: Path = Path("agent-memory.sqlite3")
    # OpenTelemetry traces: off, console, or otlp (OTEL_EXPORTER_OTLP_ENDPOINT); needs --extra maf
    travelmate_telemetry: Literal["off", "console", "otlp"] = "off"
    # Product data (accounts, trips, favourites, reviews); one SQLite file, gitignored
    travelmate_db: Path = Path("travelmate.sqlite3")
    # PostgreSQL instead of SQLite, e.g. postgresql://user:password@localhost:5432/travelmate
    # (needs --extra postgres). Contains a password: never logged or returned.
    travelmate_database_url: str = ""
    # The account signing up with this email becomes an admin
    travelmate_admin_email: str = ""
    travelmate_signup_open: bool = True
    # Optional SMTP for password-reset emails (e.g. smtp.gmail.com + an app password)
    travelmate_smtp_host: str = ""
    travelmate_smtp_port: int = 587
    travelmate_smtp_user: str = ""
    travelmate_smtp_password: str = ""
    travelmate_smtp_from: str = ""
    # Public site. The address it is served at (https://…, used for links in emails, the
    # sitemap and share previews), who runs it and how to reach them (shown on the legal pages).
    travelmate_public_url: str = ""
    travelmate_operator_name: str = ""
    travelmate_contact_email: str = ""
    # AI uses per signed-in user per day (Vietnam time); 0 = no limit. Admins and the
    # operator token are not limited. Keeps a free Gemini key from being used up by one account.
    travelmate_daily_plans: int = Field(default=10, ge=0)
    travelmate_daily_chats: int = Field(default=60, ge=0)

    @field_validator("travelmate_public_url")
    @classmethod
    def public_url_is_http(cls, value):
        value = value.strip().rstrip("/")
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("TRAVELMATE_PUBLIC_URL must start with https:// or http://")
        return value

    @field_validator("travelmate_memory_user", mode="before")
    @classmethod
    def blank_memory_user_is_unset(cls, value):
        # .env.example ships TRAVELMATE_MEMORY_USER= empty; that means "not configured".
        return None if isinstance(value, str) and not value.strip() else value


def memory_store(settings):
    if settings.travelmate_memory_user is None:
        return None
    from app.specialists.memory import MemorySpecialist

    return MemorySpecialist(settings.travelmate_memory_db, settings.travelmate_memory_user)


def planning_agent(settings):
    """LLM Planning Agent in live mode; demo mode uses the deterministic core plan."""
    if settings.travelmate_mode != "live":
        return None
    from app.agents.planning import PlanningAgent

    if settings.agent_engine == "maf":
        from app.core.llm.maf_clients import maf_gemini_client

        return PlanningAgent(lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model), "maf")
    return PlanningAgent(lambda: settings.gemini_model, "adk")


def concierge_agent(settings):
    """LLM concierge for the chat in live mode; demo mode routes by keywords."""
    if settings.travelmate_mode != "live":
        return None
    from app.agents.concierge import ConciergeAgent

    if settings.agent_engine == "maf":
        from app.core.llm.maf_clients import maf_gemini_client

        return ConciergeAgent(lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model), "maf")
    return ConciergeAgent(lambda: settings.gemini_model, "adk")


def knowledge_agent(settings):
    """Agentic RAG guide: LLM in live mode, extractive quotes from the same sources in demo mode."""
    from app.agents.guide import KnowledgeAgent, KnowledgeBase

    if settings.travelmate_mode != "live":
        return KnowledgeAgent(KnowledgeBase())
    if settings.agent_engine == "maf":
        from app.core.llm.maf_clients import maf_gemini_client

        return KnowledgeAgent(KnowledgeBase(), lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model),
                              "maf")
    return KnowledgeAgent(KnowledgeBase(), lambda: settings.gemini_model, "adk")


def live_planner(settings):
    if settings.agent_engine == "maf":
        from app.core.llm.maf_adapter import MafPlanner
        from app.core.llm.maf_clients import maf_gemini_client

        return MafPlanner(lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model))
    return AdkPlanner(settings.gemini_model)


class Services:
    """Everything the API, the MCP server and the A2A endpoint share; built once per process."""

    def __init__(self, settings, provider, orchestrator, chat, photos=None):
        self.settings, self.provider, self.orchestrator, self.chat, self.photos = (
            settings, provider, orchestrator, chat, photos)


class HidingProvider:
    """Wraps a place provider so places an admin hid never reach searches, plans or the chat."""

    def __init__(self, provider, hidden_ids):
        self.inner, self.hidden_ids = provider, hidden_ids

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def filtered(self, result):
        hidden = await asyncio.to_thread(self.hidden_ids)
        if not hidden:
            return result
        update = {"places": [p for p in result.places if p.id not in hidden]}
        if getattr(result, "stays", None):
            update["stays"] = [p for p in result.stays if p.id not in hidden]
        return result.model_copy(update=update)

    async def search(self, trip):
        return await self.filtered(await self.inner.search(trip))

    async def search_places(self, query):
        return await self.filtered(await self.inner.search_places(query))


def build_services(settings=None, orchestrator=None, provider=None, chat=None, hidden_ids=None):
    settings = settings or Settings()
    if settings.travelmate_mode == "live":
        if not settings.google_api_key or not settings.travelmate_api_token:
            raise ValueError("Live mode requires GOOGLE_API_KEY and TRAVELMATE_API_TOKEN")
        if settings.travelmate_place_provider == "google" and not settings.google_maps_api_key:
            raise ValueError("TRAVELMATE_PLACE_PROVIDER=google requires GOOGLE_MAPS_API_KEY")
        # ADK reads the key from the environment; dotenv does not export it automatically.
        import os

        os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    photos = None
    if provider is None:
        if settings.travelmate_mode == "demo":
            provider = DemoProvider()
        elif settings.travelmate_place_provider == "open_data":
            from app.tools.places.open_data_provider import OpenDataProvider

            provider = OpenDataProvider()
        else:
            photos = GooglePhotoProxy(settings.google_maps_api_key)
            provider = LiveProvider(settings.google_maps_api_key, photos=photos)
    if hidden_ids is not None:
        provider = HidingProvider(provider, hidden_ids)
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
            from app.agents.workflow_orchestrator import WorkflowOrchestrator

            orchestrator_cls = WorkflowOrchestrator
        else:
            orchestrator_cls = Orchestrator
        if settings.travelmate_orchestrator == "planning":
            from app.agents.planning import PlanningOrchestrator

            orchestrator = PlanningOrchestrator(
                registry, provider, planning_agent(settings), settings.travelmate_mode,
                settings.travelmate_agent_timeout,
            )
        else:
            orchestrator = orchestrator_cls(registry, settings.travelmate_mode, settings.travelmate_agent_timeout)
    if chat is None:
        from app.agents.concierge import ChatService

        chat = ChatService(orchestrator, provider, concierge_agent(settings), settings.travelmate_agent_timeout,
                           knowledge_agent(settings))
    return Services(settings, provider, orchestrator, chat, photos)


def create_app(settings=None, orchestrator=None, provider=None, chat=None, store=None):
    settings = settings or Settings()
    configure_telemetry(settings.travelmate_telemetry, "travelmate-api")
    if store is None:
        from app.memory.store import Store

        store = Store(settings.travelmate_database_url or settings.travelmate_db, settings.travelmate_admin_email)
    services = build_services(settings, orchestrator, provider, chat, hidden_ids=store.hidden_place_ids)
    settings, provider, orchestrator, chat, photos = (
        services.settings, services.provider, services.orchestrator, services.chat, services.photos)
    app = FastAPI(title="TravelMate API", version="0.1.0")
    app.state.chat, app.state.store = chat, store
    bearer = HTTPBearer(auto_error=False)

    async def authorize(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        # The operator's API token, or a signed-in user's session (Bearer token or HttpOnly cookie).
        if not settings.travelmate_api_token:
            return
        if credentials is not None and secrets.compare_digest(credentials.credentials, settings.travelmate_api_token):
            return
        user, _ = await session_from(request, credentials, store)
        if user is None:
            raise HTTPException(401, "Invalid API token")

    def daily_limit(kind):
        return {"plan": settings.travelmate_daily_plans, "chat": settings.travelmate_daily_chats}[kind]

    async def quota_owner(request, credentials, kind):
        """The signed-in user to charge for one AI use, or None when nobody is limited.

        Admins, the operator token and visitors on a server without accounts are not limited.
        Raises 429 when today's uses are spent. Uses are counted after success (charge()).
        """
        limit = daily_limit(kind)
        if not limit:
            return None
        if (credentials is not None and settings.travelmate_api_token
                and secrets.compare_digest(credentials.credentials, settings.travelmate_api_token)):
            return None
        user, _ = await session_from(request, credentials, store)
        if user is None or user["role"] == "admin":
            return None
        used = (await asyncio.to_thread(store.usage_today, user["id"])).get(kind, 0)
        if used >= limit:
            raise HTTPException(
                429, f"Bạn đã dùng hết {limit} {QUOTA_LABELS[kind]} của hôm nay. Hạn mức được làm mới lúc 0 giờ "
                     "(giờ Việt Nam).", headers={"Retry-After": str(seconds_to_midnight_vn())})
        return user["id"]

    async def charge(owner, kind):
        if owner is None:
            return
        try:
            await asyncio.to_thread(store.add_usage, owner, kind)
        except Exception as exc:  # counting must never fail a request that already succeeded
            logger.warning("usage outcome=failed error_type=%s", type(exc).__name__)

    def public_base(request):
        return settings.travelmate_public_url or str(request.base_url).rstrip("/")

    async def remember(places):
        try:
            await asyncio.to_thread(store.remember_places, [p.model_dump(mode="json") for p in places])
        except Exception as exc:  # the product database must never break planning
            logger.warning("store remember_places outcome=failed error_type=%s", type(exc).__name__)

    async def visible(places):
        hidden = await asyncio.to_thread(store.hidden_place_ids)
        return [p for p in places if p.id not in hidden]

    @app.get("/api/v1/places/photo", include_in_schema=False)
    async def place_photo(ref: str):
        # No bearer token: <img> tags cannot send one. Only photo names this server returned
        # in a search are resolved, so the key cannot be spent on arbitrary requests.
        if photos is None:
            raise HTTPException(404, "Photos are not enabled")
        try:
            uri = await photos.resolve(ref)
        except Exception:
            raise HTTPException(502, "Photo unavailable") from None
        if uri is None:
            raise HTTPException(404, "Unknown photo")
        return RedirectResponse(uri, status_code=302, headers={"Cache-Control": "private, max-age=3000"})

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "mode": settings.travelmate_mode,
            "token_required": bool(settings.travelmate_api_token),
            "place_provider": None if settings.travelmate_mode == "demo" else settings.travelmate_place_provider,
            "agent_engine": settings.agent_engine,
            "orchestrator": settings.travelmate_orchestrator,
            "accounts": True,
            "database": store.backend,
            "signup_open": settings.travelmate_signup_open,
        }

    @app.get("/api/v1/site")
    async def site():
        """What the public pages show: who runs the site, how to reach them, the daily limits."""
        return {
            "operator_name": settings.travelmate_operator_name,
            "contact_email": settings.travelmate_contact_email,
            "daily_plans": settings.travelmate_daily_plans,
            "daily_chats": settings.travelmate_daily_chats,
            "signup_open": settings.travelmate_signup_open,
        }

    @app.get("/api/v1/me/usage")
    async def my_usage(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        user, _ = await session_from(request, credentials, store)
        if user is None:
            raise HTTPException(401, "Bạn cần đăng nhập, hoặc phiên đăng nhập đã hết hạn.")
        used = await asyncio.to_thread(store.usage_today, user["id"])
        admin = user["role"] == "admin"
        return {kind: {"used": used.get(kind, 0), "limit": None if admin or not daily_limit(kind) else daily_limit(kind)}
                for kind in ("plan", "chat")}

    @app.post("/api/v1/places/search", response_model=PlaceResult, dependencies=[Depends(authorize)])
    async def search_places(query: PlaceSearchRequest):
        try:
            result = await provider.search_places(query)
            result = result.model_copy(update={"places": await visible(result.places)})
            await remember(result.places)
            return result
        except TimeoutError:
            raise HTTPException(504, "Place lookup timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception:
            raise HTTPException(502, "Place lookup failed") from None

    @app.post("/api/v1/plans/preview", response_model=PlanResponse, dependencies=[Depends(authorize)])
    async def preview(trip: TripRequest, request: Request,
                      credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        owner = await quota_owner(request, credentials, "plan")
        try:
            plan = await orchestrator.plan(trip)
            await remember(plan.places + plan.stays)
            await charge(owner, "plan")
            return plan
        except TimeoutError:
            raise HTTPException(504, "Agent processing timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception as exc:
            # Never expose provider URLs containing keys, prompts or stack traces; log the type
            # (and the root cause's type) so operators can tell a provider outage from a bug.
            root = exc
            while root.__cause__ is not None or root.__context__ is not None:
                root = root.__cause__ or root.__context__
            logger.warning(
                "plan_preview outcome=failed error_type=%s root_type=%s", type(exc).__name__, type(root).__name__
            )
            raise HTTPException(502, "Planning failed; check provider configuration and retry") from None

    @app.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(authorize)])
    async def chat_turn(data: ChatRequest, request: Request,
                        credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        # Signed-in users' chats are saved to the database (and plans to their trips); others stay in memory.
        charged = await quota_owner(request, credentials, "chat")
        user, _ = await session_from(request, credentials, store)
        owner = user["id"] if user else None
        trip_id = None
        try:
            session = None
            if owner and data.session_id and data.session_id not in chat.store.sessions:
                try:
                    saved = await asyncio.to_thread(store.chat, owner, data.session_id)
                    session = chat.store.put(ChatSession.load(saved["id"], owner, saved["state"]))
                except StoreError:
                    session = None  # unknown or someone else's: start a new conversation
            session, replies = await chat.handle_turn(data.session_id, data.message, owner, session)
            for reply in replies:
                if reply.places:
                    reply.places = await visible(reply.places)
                await remember(reply.places + (reply.plan.places + reply.plan.stays if reply.plan else []))
            if owner:
                title = next((m.text for m in session.messages if m.role == "user"), data.message)[:80]
                await asyncio.to_thread(store.save_chat, owner, session.id, title, session.dump())
                planned = next((r for r in replies if r.plan is not None and r.trip is not None), None)
                if planned:
                    saved_trip = await asyncio.to_thread(
                        store.save_trip, owner, planned.trip.model_dump(mode="json"),
                        planned.plan.model_dump(mode="json"),
                        f"{planned.trip.destination} · {len(planned.plan.draft.days)} ngày (Trợ lý AI)")
                    trip_id = saved_trip["id"]
        except Exception as exc:
            logger.warning("chat outcome=failed error_type=%s", type(exc).__name__)
            raise HTTPException(502, "Chat failed; retry shortly") from None
        await charge(charged, "chat")
        return ChatResponse(session_id=session.id, reply=replies[0], replies=replies,
                            active_agent=session.active_agent, trip_id=trip_id)

    from app.trust.accounts import create_accounts_router  # noqa: F811 (session_from imported at top)

    app.include_router(create_accounts_router(store, settings))

    # A2A: Agent Card + JSON-RPC endpoint over the same chat sessions (app/protocols/a2a.py)
    from app.protocols.a2a import create_a2a_router

    app.include_router(create_a2a_router(chat, settings.travelmate_api_token))

    @app.get("/", include_in_schema=False)
    async def frontend(request: Request, view: str = "home"):
        return HTMLResponse(page_html(view, public_base(request)), headers={"Cache-Control": "no-cache"})

    @app.get("/ui/travelmate-v2/index.html", include_in_schema=False)
    async def old_address(request: Request):
        # The site lives at /; old links and bookmarks keep working.
        query = request.url.query
        return RedirectResponse("/" + (f"?{query}" if query else ""), status_code=301)

    @app.get("/robots.txt", include_in_schema=False)
    async def robots(request: Request):
        return PlainTextResponse(f"User-agent: *\nDisallow: /api/\nSitemap: {public_base(request)}/sitemap.xml\n")

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request):
        base = html.escape(public_base(request))
        urls = "".join(f"<url><loc>{base}/{'' if view == 'home' else '?view=' + view}</loc></url>"
                       for view in PUBLIC_PAGES)
        return Response('<?xml version="1.0" encoding="UTF-8"?>'
                        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        # Make browsers revalidate UI files (ETag) so a restarted server never runs stale JS.
        if request.url.path.startswith("/ui/"):
            response.headers["Cache-Control"] = "no-cache"
        # Basic hardening for a public site.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    app.mount("/ui", StaticFiles(directory=FRONTEND), name="ui")
    return app
