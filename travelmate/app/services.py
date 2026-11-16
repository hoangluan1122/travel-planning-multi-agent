"""Builds the agents and data sources from Settings, once per process.

This is the one place that decides demo or live data, Google Maps or open data, ADK or
MAF, and which orchestrator puts a plan together. The web API (app/main.py), the MCP
server and the A2A endpoint all use the Services it returns.
"""

import os

from app.agents.budget import BudgetAgent
from app.agents.itinerary import PlannerAgent
from app.agents.orchestrator import Orchestrator
from app.agents.place import PlaceAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.weather import WeatherAgent
from app.core.base import Registry
from app.core.llm.adk_adapter import AdkPlanner
from app.memory.preferences import MemoryAgent
from app.settings import Settings
from app.tools.places.place_media import GooglePhotoProxy
from app.tools.places.provider_wrappers import CachingProvider, HidingProvider
from app.tools.places.providers import DemoProvider, LiveProvider


class Services:
    """Everything the API, the MCP server and the A2A endpoint share; built once per process."""

    def __init__(self, settings, provider, orchestrator, chat, photos=None):
        self.settings, self.provider, self.orchestrator, self.chat, self.photos = (
            settings, provider, orchestrator, chat, photos)


def model_factory(settings):
    """How an LLM agent gets its model: a MAF Gemini client, or (ADK) the model's name."""
    if settings.agent_engine == "maf":
        from app.core.llm.maf_clients import maf_gemini_client

        return lambda: maf_gemini_client(settings.google_api_key, settings.gemini_model)
    return lambda: settings.gemini_model


def memory_store(settings):
    """Saved preferences of the one identity the host configured, or None (request interests only)."""
    if settings.travelmate_memory_user is None:
        return None
    from app.specialists.memory import MemorySpecialist

    return MemorySpecialist(settings.travelmate_memory_db, settings.travelmate_memory_user)


def planning_agent(settings):
    """LLM Planning Agent in live mode; demo mode uses the deterministic core plan."""
    if settings.travelmate_mode != "live":
        return None
    from app.agents.planning import PlanningAgent

    return PlanningAgent(model_factory(settings), settings.agent_engine)


def concierge_agent(settings):
    """LLM concierge for the chat in live mode; demo mode routes by keywords."""
    if settings.travelmate_mode != "live":
        return None
    from app.agents.concierge import ConciergeAgent

    return ConciergeAgent(model_factory(settings), settings.agent_engine)


def knowledge_agent(settings):
    """Agentic RAG guide: LLM in live mode, extractive quotes from the same sources in demo mode."""
    from app.agents.guide import KnowledgeAgent, KnowledgeBase

    if settings.travelmate_mode != "live":
        return KnowledgeAgent(KnowledgeBase())
    return KnowledgeAgent(KnowledgeBase(), model_factory(settings), settings.agent_engine)


def live_planner(settings):
    """The LLM that schedules the days, on the configured engine."""
    if settings.agent_engine == "maf":
        from app.core.llm.maf_adapter import MafPlanner

        return MafPlanner(model_factory(settings))
    return AdkPlanner(settings.gemini_model)


def check_live_settings(settings):
    if not settings.google_api_key or not settings.travelmate_api_token:
        raise ValueError("Live mode requires GOOGLE_API_KEY and TRAVELMATE_API_TOKEN")
    if settings.travelmate_place_provider == "google" and not settings.google_maps_api_key:
        raise ValueError("TRAVELMATE_PLACE_PROVIDER=google requires GOOGLE_MAPS_API_KEY")
    # ADK reads the key from the environment; dotenv does not export it automatically.
    os.environ["GOOGLE_API_KEY"] = settings.google_api_key


def place_provider(settings, place_cache=None):
    """(provider, Google photo proxy or None) for the configured mode and source."""
    if settings.travelmate_mode == "demo":
        return DemoProvider(), None
    photos = None
    if settings.travelmate_place_provider == "open_data":
        from app.tools.places.open_data_provider import OpenDataProvider

        provider = OpenDataProvider()
    else:
        photos = GooglePhotoProxy(settings.google_maps_api_key)
        provider = LiveProvider(settings.google_maps_api_key, photos=photos)
    if place_cache is not None:
        provider = CachingProvider(provider, place_cache, settings.travelmate_place_provider)
    return provider, photos


def plan_orchestrator(settings, provider):
    """The agents that make a plan, run by the orchestrator TRAVELMATE_ORCHESTRATOR names."""
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
    mode, timeout = settings.travelmate_mode, settings.travelmate_agent_timeout
    if settings.travelmate_orchestrator == "planning":
        from app.agents.planning import PlanningOrchestrator

        return PlanningOrchestrator(registry, provider, planning_agent(settings), mode, timeout)
    if settings.travelmate_orchestrator == "workflow":
        try:
            import agent_framework  # noqa: F401
        except ImportError:
            raise ValueError("TRAVELMATE_ORCHESTRATOR=workflow requires the maf extra") from None
        from app.agents.workflow_orchestrator import WorkflowOrchestrator

        return WorkflowOrchestrator(registry, mode, timeout)
    return Orchestrator(registry, mode, timeout)


def build_services(settings=None, orchestrator=None, provider=None, chat=None, hidden_ids=None, place_cache=None):
    """Wire everything up. Tests pass their own orchestrator, provider or chat to replace a part.

    hidden_ids: a function returning the ids of places an admin hid (filtered everywhere).
    place_cache: the product database, used to keep place searches for a day (live mode only).
    """
    settings = settings or Settings()
    if settings.travelmate_mode == "live":
        check_live_settings(settings)
    photos = None
    if provider is None:
        provider, photos = place_provider(settings, place_cache)
    if hidden_ids is not None:
        provider = HidingProvider(provider, hidden_ids)
    if orchestrator is None:
        orchestrator = plan_orchestrator(settings, provider)
    if chat is None:
        from app.agents.concierge import ChatService

        chat = ChatService(orchestrator, provider, concierge_agent(settings), settings.travelmate_agent_timeout,
                           knowledge_agent(settings))
    return Services(settings, provider, orchestrator, chat, photos)
