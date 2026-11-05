import json
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from app.a2a import agent_card
from app.chat import ChatService
from app.knowledge import Citation, KnowledgeAnswer
from app.main import Settings, build_services, create_app
from app.mcp_server import create_mcp
from app.models import Place, PlaceResult, WeatherDay, WeatherResult
from app.providers import DemoProvider


class Provider(DemoProvider):
    def __init__(self, fail=False):
        self.fail = fail

    async def search_places(self, query):
        if self.fail:
            raise RuntimeError("https://maps.example/?key=SECRET exploded")
        return PlaceResult(places=[Place(id="p1", name="Lăng Tự Đức", address="Huế", latitude=16.43, longitude=107.56,
                                         source="osm", types=["tomb"])])

    async def forecast(self, trip):
        return WeatherResult(days=[WeatherDay(date=trip.start_date, weather_code=61)])


class Guide:
    async def ask(self, question, context, destination=None):
        return KnowledgeAnswer(status="answered", text="Lăng xây từ 1864.", citations=[
            Citation(id="w1", source="wikipedia", title="Lăng Tự Đức", url="https://vi.wikipedia.org/wiki/L")])


def services(provider=None):
    built = build_services(Settings(_env_file=None), provider=provider or Provider())
    built.chat.guide = Guide()
    return built


def payload(result):
    assert not result.isError, result.content
    return result.structuredContent.get("result", result.structuredContent) if result.structuredContent else (
        json.loads(result.content[0].text))


# --- MCP ------------------------------------------------------------------------------------


async def test_mcp_lists_tools_with_schemas_and_the_ticket_resource():
    async with create_connected_server_and_client_session(create_mcp(services())) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_places", "weather_forecast", "ask_guide", "plan_trip"}
        assert tools["search_places"].inputSchema["properties"]["category"]["enum"] == [
            "attraction", "restaurant", "hotel"]
        assert set(tools["plan_trip"].inputSchema["required"]) >= {"destination", "start_date", "travelers"}
        resource = await client.read_resource("travelmate://tickets")
        assert "Lăng Tự Đức" in resource.contents[0].text or "lăng tự đức" in resource.contents[0].text


async def test_mcp_search_places_adds_cited_tickets():
    async with create_connected_server_and_client_session(create_mcp(services())) as client:
        data = payload(await client.call_tool("search_places", {"destination": "Huế"}))
        place = data["places"][0]
        assert place["name"] == "Lăng Tự Đức" and place["ticket"]["adult_vnd"] == 150000
        assert place["ticket"]["sources"][0].startswith("https://")


async def test_mcp_weather_and_guide():
    async with create_connected_server_and_client_session(create_mcp(services())) as client:
        weather = payload(await client.call_tool("weather_forecast", {"destination": "Huế"}))
        assert weather["days"][0]["summary"] == "mưa" and weather["source"] == "Open-Meteo"
        answer = payload(await client.call_tool("ask_guide", {"question": "Lăng Tự Đức có gì?"}))
        assert answer["citations"][0]["url"].startswith("https://vi.wikipedia.org/")


async def test_mcp_plan_trip_returns_a_compact_plan():
    start = date.today() + timedelta(days=3)
    async with create_connected_server_and_client_session(create_mcp(services())) as client:
        plan = payload(await client.call_tool("plan_trip", {
            "destination": "Huế", "start_date": start.isoformat(), "end_date": (start + timedelta(1)).isoformat(),
            "travelers": 2, "budget_vnd": 5000000}))
        assert len(plan["days"]) == 2 and plan["mode"] == "demo" and "unknown_items" in plan["budget"]


async def test_mcp_errors_never_leak_provider_details():
    async with create_connected_server_and_client_session(create_mcp(services(Provider(fail=True)))) as client:
        result = await client.call_tool("search_places", {"destination": "Huế"})
        assert result.isError and "SECRET" not in result.content[0].text and "retry" in result.content[0].text
        past = await client.call_tool("plan_trip", {"destination": "Huế", "start_date": "2020-01-01",
                                                    "end_date": "2020-01-02", "travelers": 1, "budget_vnd": 1})
        assert past.isError and "Invalid input" in past.content[0].text


# --- A2A ------------------------------------------------------------------------------------


def a2a_client(token=""):
    built = services()
    settings = Settings(_env_file=None, travelmate_api_token=token)
    chat = ChatService(built.orchestrator, built.provider, guide=Guide())
    return TestClient(create_app(settings, orchestrator=built.orchestrator, provider=built.provider, chat=chat))


def send(client, text, context_id=None, task_id=None, headers=None, request_id=1):
    message = {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": str(uuid.uuid4())}
    if context_id:
        message["contextId"] = context_id
    if task_id:
        message["taskId"] = task_id
    body = {"jsonrpc": "2.0", "id": request_id, "method": "SendMessage", "params": {"message": message}}
    return client.post("/a2a", json=body, headers=headers or {})


def test_agent_card_follows_a2a_1_0():
    card = a2a_client().get("/.well-known/agent-card.json").json()
    for field in ["name", "description", "supportedInterfaces", "version", "capabilities", "defaultInputModes",
                  "defaultOutputModes", "skills"]:
        assert field in card
    interface = card["supportedInterfaces"][0]
    assert interface == {"url": "http://testserver/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    assert all({"id", "name", "description", "tags"} <= set(s) for s in card["skills"])
    assert "securitySchemes" not in card
    assert agent_card("http://x", True)["securitySchemes"]["bearerAuth"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"


def test_trip_details_over_two_messages_continue_one_task():
    client = a2a_client()
    first = send(client, "lên lịch trình đi Huế").json()["result"]["task"]
    assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert first["status"]["message"]["metadata"]["specialist"] == "trip_planner"
    start = date.today() + timedelta(days=5)
    text = f"từ {start:%d/%m} đến {start + timedelta(1):%d/%m}, 2 người, 5 triệu"
    second = send(client, text, first["contextId"], first["id"]).json()["result"]["task"]
    assert second["id"] == first["id"] and second["status"]["state"] == "TASK_STATE_COMPLETED"
    plan = next(a for a in second["artifacts"] if a["name"] == "plan")["parts"][0]
    assert plan["mediaType"] == "application/json" and len(plan["data"]["days"]) == 2
    assert [m["role"] for m in second["history"]] == ["ROLE_USER", "ROLE_AGENT"] * 2
    fetched = client.post("/a2a", json={"jsonrpc": "2.0", "id": 9, "method": "GetTask",
                                        "params": {"id": first["id"], "historyLength": 1}}).json()["result"]
    assert len(fetched["history"]) == 1 and fetched["status"]["state"] == "TASK_STATE_COMPLETED"


def test_places_and_citations_come_back_as_artifacts():
    client = a2a_client()
    places = send(client, "tìm chỗ tham quan ở Huế").json()["result"]["task"]
    assert places["status"]["state"] == "TASK_STATE_COMPLETED"
    assert places["artifacts"][0]["name"] == "places"
    guide = send(client, "Lăng Tự Đức có gì đặc biệt?", places["contextId"]).json()["result"]["task"]
    assert guide["id"] != places["id"] and guide["contextId"] == places["contextId"]
    assert guide["artifacts"][0]["name"] == "citations"


@pytest.mark.parametrize("body,code", [
    ({"jsonrpc": "2.0", "id": 1, "method": "Nope"}, -32601),
    ({"jsonrpc": "2.0", "id": 1, "method": "SendStreamingMessage", "params": {}}, -32004),
    ({"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "missing"}}, -32001),
    ({"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {"role": "ROLE_AGENT"}}}, -32602),
    ({"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
        "role": "ROLE_USER", "messageId": "m", "parts": [{"data": {}}]}}}, -32602),
    ({"id": 1, "method": "SendMessage"}, -32600),
])
def test_json_rpc_errors(body, code):
    assert a2a_client().post("/a2a", json=body).json()["error"]["code"] == code


def test_finished_task_cannot_be_continued_and_unknown_task_is_reported():
    client = a2a_client()
    done = send(client, "tìm chỗ tham quan ở Huế").json()["result"]["task"]
    assert send(client, "nữa", done["contextId"], done["id"]).json()["error"]["code"] == -32602
    assert send(client, "nữa", task_id="nope").json()["error"]["code"] == -32001


def test_auth_and_version_header():
    client = a2a_client(token="secret")
    assert client.get("/.well-known/agent-card.json").status_code == 200  # the card is public
    assert send(client, "xin chào").status_code == 401
    ok = send(client, "xin chào", headers={"Authorization": "Bearer secret", "A2A-Version": "1.0"})
    assert ok.json()["result"]["task"]["status"]["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_INPUT_REQUIRED")
    old = send(client, "xin chào", headers={"Authorization": "Bearer secret", "A2A-Version": "0.3"})
    assert old.status_code == 400 and old.json()["supportedVersions"] == ["1.0"]


def test_specialist_failure_is_a_failed_task():
    built = services(Provider(fail=True))
    chat = ChatService(built.orchestrator, built.provider, guide=Guide())
    failing = TestClient(create_app(Settings(_env_file=None), orchestrator=built.orchestrator,
                                    provider=built.provider, chat=chat))
    task = send(failing, "tìm quán ăn ở Huế").json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_FAILED"
