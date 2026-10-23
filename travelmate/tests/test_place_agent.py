import asyncio

import pytest

pytest.importorskip("google.adk")
from fastapi.testclient import TestClient
from test_adk_tools import ScriptedModel

from app.agents import AgentError
from app.models import Context, Place, PlaceResult
from app.place_agent import PlaceAgentInput, PlaceAssistant
from app.place_api import PlaceSettings, create_app


class Provider:
    def __init__(self, empty=False, broken=False):
        self.empty, self.broken = empty, broken
        self.searches = self.details = 0

    async def search_places(self, query):
        self.searches += 1
        if self.broken:
            raise AgentError("private provider failure")
        return PlaceResult(
            places=[]
            if self.empty
            else [
                Place(
                    id=query.destination,
                    name="Provider name",
                    address="Provider address",
                    latitude=16,
                    longitude=108,
                    source="test_fixture",
                )
            ]
        )

    async def get_details(self, place_id):
        self.details += 1
        return Place(
            id=place_id,
            name="Updated provider name",
            address="Updated address",
            latitude=16,
            longitude=108,
            source="test_fixture",
        )


def call(name, **args):
    return {"name": name, "args": args}


def assistant(provider, calls, **kwargs):
    return PlaceAssistant(lambda: ScriptedModel(calls=calls), provider, **kwargs)


@pytest.mark.asyncio
async def test_grounded_selection_repairs_invented_id_and_fetches_details():
    provider = Provider()
    agent = assistant(
        provider,
        [
            call("search_places", keyword="museum"),
            call("get_place_details", place_id="invented"),
            call("get_place_details", place_id="Hanoi"),
            call("submit_places", place_ids=["invented"]),
            call("submit_places", place_ids=["Hanoi"]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == "candidates"
    assert result.places[0].name == "Updated provider name"
    assert result.places[0].estimated_visit_cost_vnd is None
    assert provider.details == 1  # Unknown ID never reaches the external service.


@pytest.mark.asyncio
@pytest.mark.parametrize("broken,status", [(False, "no_results"), (True, "provider_error")])
async def test_empty_and_outage_are_distinct(broken, status):
    agent = assistant(
        Provider(empty=True, broken=broken),
        [
            call("search_places", keyword=""),
            call("submit_places", place_ids=[]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == status
    assert result.places == []


@pytest.mark.asyncio
async def test_plain_text_not_accepted():
    with pytest.raises(AgentError, match="without validated"):
        await assistant(Provider(), []).run(PlaceAgentInput(destination="Hanoi"), Context())


@pytest.mark.asyncio
async def test_search_budget():
    provider = Provider()
    with pytest.raises(AgentError, match="search budget"):
        await assistant(provider, [call("search_places", keyword="")] * 4).run(
            PlaceAgentInput(destination="Hanoi"), Context()
        )
    assert provider.searches == 3


@pytest.mark.asyncio
async def test_model_budget():
    with pytest.raises(AgentError, match="model-call budget"):
        await assistant(Provider(), [call("search_places", keyword="")] * 3, max_llm_calls=2).run(
            PlaceAgentInput(destination="Hanoi"), Context()
        )


@pytest.mark.asyncio
async def test_duplicate_submission_can_be_repaired():
    agent = assistant(
        Provider(),
        [
            call("submit_places", place_ids=[]),
            call("search_places", keyword=""),
            call("submit_places", place_ids=["Hanoi", "Hanoi"]),
            call("submit_places", place_ids=["Hanoi"]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert len(result.places) == 1


@pytest.mark.asyncio
async def test_detail_failure_preserves_search_evidence_as_partial():
    class FailedDetails(Provider):
        async def get_details(self, place_id):
            raise AgentError("private failure")

    agent = assistant(
        FailedDetails(),
        [
            call("search_places", keyword=""),
            call("get_place_details", place_id="Hanoi"),
            call("submit_places", place_ids=["Hanoi"]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == "partial"
    assert result.places[0].name == "Provider name"
    assert "private failure" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_submission_budget():
    agent = assistant(Provider(), [call("submit_places", place_ids=[])] * 4)
    with pytest.raises(AgentError, match="submission budget"):
        await agent.run(PlaceAgentInput(destination="Hanoi"), Context())


def test_missing_credentials_fail_closed():
    with pytest.raises(ValueError, match="API_TOKEN"):
        create_app(PlaceSettings(_env_file=None, travelmate_api_token=""))
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        create_app(
            PlaceSettings(
                _env_file=None, travelmate_api_token="test", google_api_key="", google_maps_api_key=""
            )
        )


@pytest.mark.asyncio
async def test_timeout_cancels_provider():
    cancelled = asyncio.Event()

    class Slow(Provider):
        async def search_places(self, query):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

    with pytest.raises(TimeoutError):
        await assistant(Slow(), [call("search_places", keyword="")]).run(
            PlaceAgentInput(destination="Hanoi"), Context(), timeout=0.2
        )
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_concurrent_invocations_use_separate_evidence():
    # The same assistant instance serves concurrent requests. Each model and
    # evidence dictionary must still be created per invocation.
    calls = [call("search_places", keyword=""), call("submit_places", place_ids=["Hanoi"])]
    shared = assistant(Provider(), calls)

    async def run(destination):
        return await shared.run(PlaceAgentInput(destination=destination), Context())

    a, b = await asyncio.gather(run("Hanoi"), run("Hanoi"))
    assert a.places[0].id == "Hanoi"
    assert b.places[0].id == "Hanoi"
    assert a.request_id != b.request_id
    assert a.search_calls == b.search_calls == 1


def test_api_auth_and_input_validation():
    agent = assistant(
        Provider(),
        [
            call("search_places", keyword=""),
            call("submit_places", place_ids=["Hanoi"]),
        ],
    )
    client = TestClient(create_app(PlaceSettings(_env_file=None, travelmate_api_token="token"), agent))
    assert client.post("/api/v1/agent/places", json={"destination": "Hanoi"}).status_code == 401
    headers = {"Authorization": "Bearer token"}
    assert client.post("/api/v1/agent/places", headers=headers, json={"destination": "  "}).status_code == 422
    response = client.post("/api/v1/agent/places", headers=headers, json={"destination": "Hanoi"})
    assert response.status_code == 200
    assert response.json()["status"] == "candidates"


@pytest.mark.asyncio
async def test_invalid_provider_record_is_not_accepted_as_evidence():
    class InvalidProvider(Provider):
        async def search_places(self, query):
            result = await super().search_places(query)
            result.places[0].latitude = 999
            return result

    agent = assistant(
        InvalidProvider(),
        [
            call("search_places", keyword=""),
            call("submit_places", place_ids=[]),
        ],
    )
    result = await agent.run(PlaceAgentInput(destination="Hanoi"), Context())
    assert result.status == "provider_error"
    assert result.places == []
