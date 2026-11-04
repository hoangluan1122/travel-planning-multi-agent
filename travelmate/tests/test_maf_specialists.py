"""Place and Recommendation agents on the MAF engine keep the ADK guarantees.

Scenarios mirror test_place_agent.py, test_specialist_llm.py and the LLM test in
test_live_place_agent.py, replayed through MAF's real function-invocation loop.
"""

import asyncio

import pytest

pytest.importorskip("agent_framework")
from test_live_place_agent import URL, Web, discovery, record
from test_maf_tools import ScriptedClient
from test_place_agent import Provider, call

from app.agents import AgentError
from app.live_place_agent import LivePlaceAgent, LivePlaceRequest
from app.models import Context, Place
from app.place_agent import PlaceAgentInput, PlaceAssistant
from app.specialists.recommendation import RecommendationRequest, RecommendationSpecialist


def place(identity="p1"):
    return Place(id=identity, name="Source name", address="Source address", latitude=0, longitude=0, source="fixture")


def maf_assistant(provider, calls, clients=None, **kwargs):
    def factory():
        client = ScriptedClient(calls)
        if clients is not None:
            clients.append(client)
        return client

    return PlaceAssistant(factory, provider, engine="maf", **kwargs)


# --- Place agent ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_grounded_selection_repairs_invented_id_and_fetches_details():
    provider = Provider()
    clients = []
    agent = maf_assistant(
        provider,
        [
            call("search_places", keyword="museum"),
            call("get_place_details", place_id="invented"),
            call("get_place_details", place_id="Hanoi"),
            call("submit_places", place_ids=["invented"]),
            call("submit_places", place_ids=["Hanoi"]),
        ],
        clients,
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == "candidates"
    assert result.places[0].name == "Updated provider name"
    assert provider.details == 1
    assert clients[0].index == 5  # stops right after acceptance


@pytest.mark.asyncio
@pytest.mark.parametrize("broken,status", [(False, "no_results"), (True, "provider_error")])
async def test_place_empty_and_outage_are_distinct(broken, status):
    agent = maf_assistant(
        Provider(empty=True, broken=broken),
        [call("search_places", keyword=""), call("submit_places", place_ids=[])],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == status and result.places == []


@pytest.mark.asyncio
async def test_place_plain_text_not_accepted():
    with pytest.raises(AgentError, match="without validated"):
        await maf_assistant(Provider(), []).run(PlaceAgentInput(destination="Hanoi"), Context())


@pytest.mark.asyncio
async def test_place_search_budget_aborts_run():
    provider = Provider()
    with pytest.raises(AgentError, match="search budget"):
        await maf_assistant(provider, [call("search_places", keyword="")] * 5).run(
            PlaceAgentInput(destination="Hanoi"), Context()
        )
    assert provider.searches == 3


@pytest.mark.asyncio
async def test_place_model_budget():
    clients = []
    with pytest.raises(AgentError, match="model-call budget"):
        await maf_assistant(
            Provider(), [call("search_places", keyword="")] * 3, clients, max_llm_calls=2
        ).run(PlaceAgentInput(destination="Hanoi"), Context())
    assert clients[0].index == 2


@pytest.mark.asyncio
async def test_place_submission_budget():
    agent = maf_assistant(Provider(), [call("submit_places", place_ids=[])] * 5)
    with pytest.raises(AgentError, match="submission budget"):
        await agent.run(PlaceAgentInput(destination="Hanoi"), Context())


@pytest.mark.asyncio
async def test_place_detail_failure_preserves_search_evidence_as_partial():
    class FailedDetails(Provider):
        async def get_details(self, place_id):
            raise AgentError("private failure")

    agent = maf_assistant(
        FailedDetails(),
        [
            call("search_places", keyword=""),
            call("get_place_details", place_id="Hanoi"),
            call("submit_places", place_ids=["Hanoi"]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == "partial"
    assert "private failure" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_place_timeout_cancels_provider():
    cancelled = asyncio.Event()

    class Slow(Provider):
        async def search_places(self, query):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

    with pytest.raises(TimeoutError):
        await maf_assistant(Slow(), [call("search_places", keyword="")]).run(
            PlaceAgentInput(destination="Hanoi"), Context(), timeout=0.2
        )
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_place_concurrent_invocations_use_separate_evidence():
    shared = maf_assistant(
        Provider(), [call("search_places", keyword=""), call("submit_places", place_ids=["Hanoi"])]
    )
    a, b = await asyncio.gather(
        shared.run(PlaceAgentInput(destination="Hanoi"), Context()),
        shared.run(PlaceAgentInput(destination="Hanoi"), Context()),
    )
    assert a.request_id != b.request_id
    assert a.search_calls == b.search_calls == 1


@pytest.mark.asyncio
async def test_live_place_maf_engine_reports_maf_mode():
    p = record()

    class Reader:
        async def read(self, url, destination):
            return record()

    client = ScriptedClient(
        [
            {"name": "search_places", "args": {"keyword": ""}},
            {"name": "get_place_details", "args": {"place_id": p.id}},
            {"name": "submit_places", "args": {"place_ids": ["invented"]}},
            {"name": "submit_places", "args": {"place_ids": [p.id]}},
        ]
    )
    result = await LivePlaceAgent(
        model_factory=lambda: client, web_tool=Web([discovery()]), reader=Reader(), engine="maf"
    ).run(LivePlaceRequest(destination="Sa Pa"), Context())
    assert result.status == "success" and result.execution_mode == "maf_llm"
    assert result.places[0].source_url == URL
    assert any(o.get("accepted") is False for o in client.observations)


# --- Recommendation --------------------------------------------------------------


def recommender(calls, **kwargs):
    client = ScriptedClient(calls)
    return client, RecommendationSpecialist(lambda: client, engine="maf", **kwargs)


@pytest.mark.asyncio
async def test_recommendation_repairs_ids_without_rewriting_facts():
    client, agent = recommender(
        [
            {"name": "inspect_candidates", "args": {}},
            {"name": "submit_ranking", "args": {"place_ids": ["invented"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
        ]
    )
    result = await agent.run(RecommendationRequest(candidates=[place()]), Context())
    assert result.places[0].name == "Source name"
    assert any(o.get("accepted") is False for o in client.observations)
    assert client.index == 3


@pytest.mark.asyncio
async def test_recommendation_rejects_text_only():
    _, agent = recommender([])
    with pytest.raises(AgentError, match="without validated"):
        await agent.run(RecommendationRequest(candidates=[place()]), Context())


@pytest.mark.asyncio
async def test_recommendation_cannot_select_excluded_or_omit_required():
    client, agent = recommender(
        [
            {"name": "inspect_candidates", "args": {}},
            {"name": "submit_ranking", "args": {"place_ids": ["p2"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p3"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
        ]
    )
    result = await agent.run(
        RecommendationRequest(
            candidates=[place("p1"), place("p2"), place("p3")],
            required_place_ids=["p1"],
            excluded_place_ids=["p2"],
        ),
        Context(),
    )
    assert [p.id for p in result.places] == ["p1"]
    assert any(o.get("error") == "Required places missing" for o in client.observations)


@pytest.mark.asyncio
async def test_recommendation_read_budget_aborts_run():
    _, agent = recommender([{"name": "inspect_candidates", "args": {}}] * 4)
    with pytest.raises(AgentError, match="read budget"):
        await agent.run(RecommendationRequest(candidates=[place()]), Context())


@pytest.mark.asyncio
async def test_recommendation_model_budget_is_domain_error():
    client, agent = recommender([{"name": "inspect_candidates", "args": {}}] * 2, max_llm_calls=1)
    with pytest.raises(AgentError, match="model-call budget"):
        await agent.run(RecommendationRequest(candidates=[place()]), Context())
    assert client.index == 1


# --- Settings ---------------------------------------------------------------------


def test_agent_engine_accepts_legacy_planner_engine_name(tmp_path, monkeypatch):
    from test_specialist_api import settings

    assert settings(tmp_path, agent_engine="maf").agent_engine == "maf"
    assert settings(tmp_path, planner_engine="maf").agent_engine == "maf"
    monkeypatch.setenv("PLANNER_ENGINE", "maf")
    assert settings(tmp_path).agent_engine == "maf"
    monkeypatch.setenv("AGENT_ENGINE", "adk")
    monkeypatch.delenv("PLANNER_ENGINE")
    assert settings(tmp_path).agent_engine == "adk"


def test_specialist_api_recommendation_uses_maf_engine(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient
    from test_specialist_api import HEADERS, settings

    import app.specialist_api as api

    used = []

    @asynccontextmanager
    async def scripted_factory(_settings):
        used.append("maf")
        yield lambda: ScriptedClient(
            [
                {"name": "inspect_candidates", "args": {}},
                {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
            ]
        )

    monkeypatch.setattr(api, "maf_gemini_factory", scripted_factory)
    body = RecommendationRequest(candidates=[place()]).model_dump(mode="json")
    with TestClient(api.create_app(settings(tmp_path, agent_engine="maf"))) as client:
        response = client.post("/api/v1/agents/recommendation", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert used == ["maf"]
    assert response.json()["places"][0]["id"] == "p1"
