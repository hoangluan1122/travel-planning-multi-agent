"""Configuration read from the environment and `.env` (pydantic-settings).

Every option of the server is listed here with what it does. Values that hold a secret
(API keys, the database URL, the SMTP password) are never logged or returned by the API.
"""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Mode and AI model ---------------------------------------------------------------
    # demo: labelled sample data, no keys needed; live: real sources and Gemini.
    travelmate_mode: Literal["demo", "live"] = "demo"
    # Operator token: full API access without an account (scripts, the live check).
    travelmate_api_token: str = ""
    # Seconds one agent step may take before the request fails with 504.
    travelmate_agent_timeout: float = 45
    google_api_key: str = ""
    google_maps_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    # Agent framework running the LLM agents: Google ADK or Microsoft Agent Framework.
    agent_engine: Literal["adk", "maf"] = Field(
        default="adk", validation_alias=AliasChoices("agent_engine", "planner_engine")
    )
    # How a plan is put together:
    # classic: asyncio pipeline in app/agents/orchestrator.py; workflow: MAF Workflow graph (needs --extra maf);
    # planning: Planning pattern (LLM decomposes the request into subtasks, re-plans on misses).
    travelmate_orchestrator: Literal["classic", "workflow", "planning"] = "classic"
    # Live place/weather source: google (Places API, needs GOOGLE_MAPS_API_KEY) or
    # open_data (OpenStreetMap/Photon + Open-Meteo, no key).
    travelmate_place_provider: Literal["google", "open_data"] = "google"

    # --- Memory and tracing --------------------------------------------------------------
    # Saved preferences for planning (read-only). The host binds one authenticated identity;
    # requests cannot choose whose memory is read. Unset = request interests only.
    travelmate_memory_user: UUID | None = None
    travelmate_memory_db: Path = Path("agent-memory.sqlite3")
    # OpenTelemetry traces: off, console, or otlp (OTEL_EXPORTER_OTLP_ENDPOINT); needs --extra maf.
    travelmate_telemetry: Literal["off", "console", "otlp"] = "off"

    # --- Product database and accounts ---------------------------------------------------
    # Product data (accounts, trips, favourites, reviews); one SQLite file, gitignored.
    travelmate_db: Path = Path("travelmate.sqlite3")
    # PostgreSQL instead of SQLite, e.g. postgresql://user:password@localhost:5432/travelmate
    # (needs --extra postgres). Contains a password: never logged or returned.
    travelmate_database_url: str = ""
    # The account signing up with this email becomes an admin.
    travelmate_admin_email: str = ""
    travelmate_signup_open: bool = True
    # Optional SMTP for password-reset emails (e.g. smtp.gmail.com + an app password).
    travelmate_smtp_host: str = ""
    travelmate_smtp_port: int = 587
    travelmate_smtp_user: str = ""
    travelmate_smtp_password: str = ""
    travelmate_smtp_from: str = ""

    # --- Public site -----------------------------------------------------------------------
    # The address it is served at (https://…, used for links in emails, the sitemap and share
    # previews), who runs it and how to reach them (shown on the legal pages).
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
