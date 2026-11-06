"""TravelMate as an A2A agent (course lesson 11: Agent-to-Agent protocol, A2A 1.0, JSON-RPC binding).

Other agents discover TravelMate through its Agent Card and talk to it in tasks:

    GET  /.well-known/agent-card.json   public Agent Card (skills, endpoint, auth scheme)
    POST /a2a                           JSON-RPC 2.0: SendMessage, GetTask

Each SendMessage runs one turn of the multi-agent chat (concierge + specialists). The A2A
contextId is the chat session, so a remote agent can describe a trip over several messages:
when TravelMate needs more details the task ends in TASK_STATE_INPUT_REQUIRED and the next
message (same contextId) continues it. Places, plans and citations come back as JSON
artifacts next to the text answer.

Not implemented (answered with UnsupportedOperationError): streaming, push notifications,
cancelling and listing tasks. Tasks are kept in memory.
"""

import logging
import secrets
import uuid
from collections import OrderedDict
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.protocols.summaries import place_summary, plan_summary

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS = {"1.0", "1"}
MAX_TASKS = 500
MAX_TEXT = 1000
PARAGRAPH = chr(10) * 2

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
TASK_NOT_FOUND, UNSUPPORTED_OPERATION, CONTENT_TYPE_NOT_SUPPORTED = -32001, -32004, -32005
KNOWN_UNSUPPORTED = {"SendStreamingMessage", "CancelTask", "ListTasks", "SubscribeToTask",
                     "CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig",
                     "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig", "GetExtendedAgentCard"}

SKILLS = [
    {"id": "find_places", "name": "Find places",
     "description": "Find real sights, restaurants or stays in a Vietnamese city (OpenStreetMap), with cited fees.",
     "tags": ["places", "restaurants", "hotels", "vietnam"],
     "examples": ["Tìm quán chay ở Huế", "Find seafood restaurants in Da Nang"]},
    {"id": "plan_trip", "name": "Plan a trip",
     "description": "Collect trip details over several messages, then plan a day-by-day itinerary that checks "
                    "itself against the stated wishes, meals and rain.",
     "tags": ["itinerary", "planning"],
     "examples": ["Lên lịch đi Huế từ 20/11 đến 21/11, 2 người, 5 triệu"]},
    {"id": "trip_costs", "name": "Trip costs",
     "description": "Known and estimated costs of the last planned trip; unknown items are listed, never zero.",
     "tags": ["budget"], "examples": ["Chi phí bao nhiêu?"]},
    {"id": "weather", "name": "Weather", "description": "Daily forecast for the destination (Open-Meteo).",
     "tags": ["weather"], "examples": ["Thời tiết Huế thế nào?"]},
    {"id": "travel_guide", "name": "Travel guide",
     "description": "Answers about a sight or city from Wikipedia, Wikivoyage and a cited ticket table, with "
                    "citations; never invents fees or opening hours.",
     "tags": ["rag", "guide", "tickets"], "examples": ["Lăng Tự Đức có gì đặc biệt, giá vé bao nhiêu?"]},
]


def agent_card(base_url, token_required):
    card = {
        "name": "TravelMate",
        "description": "Vietnamese travel assistant: a concierge hands each message to a specialist for places, "
                       "itineraries, costs, weather or cited travel facts. Free, cited data sources.",
        "supportedInterfaces": [{"url": f"{base_url}/a2a", "protocolBinding": "JSONRPC",
                                 "protocolVersion": PROTOCOL_VERSION}],
        "provider": {"organization": "TravelMate (demo)",
                     "url": "https://github.com/hoangluan1122/travel-planning-multi-agent"},
        "version": "0.1.0",
        "documentationUrl": "https://github.com/hoangluan1122/travel-planning-multi-agent/blob/main/docs/mcp-a2a.md",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": SKILLS,
    }
    if token_required:
        card["securitySchemes"] = {"bearerAuth": {"httpAuthSecurityScheme": {
            "scheme": "Bearer", "description": "TRAVELMATE_API_TOKEN configured on the server"}}}
    return card


def now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def rpc_error(request_id, code, message):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def rpc_result(request_id, result):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def needs_input(reply):
    return (reply.agent == "trip_planner" and reply.plan is None) or reply.text.rstrip().endswith("?")


def task_state(reply):
    if reply.failed:
        return "TASK_STATE_FAILED"
    return "TASK_STATE_INPUT_REQUIRED" if needs_input(reply) else "TASK_STATE_COMPLETED"


def artifacts_for(reply):
    out = []
    if reply.places:
        out.append({"artifactId": str(uuid.uuid4()), "name": "places",
                    "parts": [{"data": [place_summary(p) for p in reply.places], "mediaType": "application/json"}]})
    if reply.plan is not None:
        out.append({"artifactId": str(uuid.uuid4()), "name": "plan",
                    "parts": [{"data": plan_summary(reply.plan), "mediaType": "application/json"}]})
    if reply.citations:
        out.append({"artifactId": str(uuid.uuid4()), "name": "citations",
                    "parts": [{"data": [c.model_dump(mode="json") for c in reply.citations],
                               "mediaType": "application/json"}]})
    return out


def message_text(message):
    """Text of an A2A user message, or an error string."""
    if not isinstance(message, dict) or message.get("role") != "ROLE_USER":
        return None, "params.message must be a message with role ROLE_USER"
    if not isinstance(message.get("messageId"), str) or not message["messageId"]:
        return None, "params.message.messageId is required"
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        return None, "params.message.parts must be a non-empty list"
    texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if not texts:
        return None, "Only text parts are supported"
    text = "\n".join(texts).strip()
    if not text or len(text) > MAX_TEXT:
        return None, f"Message text must be 1-{MAX_TEXT} characters"
    return text, None


def create_a2a_router(chat, token):
    router = APIRouter()
    tasks: OrderedDict[str, dict] = OrderedDict()

    def keep(task):
        tasks[task["id"]] = task
        tasks.move_to_end(task["id"])
        while len(tasks) > MAX_TASKS:
            tasks.popitem(last=False)

    def trimmed(task, history_length):
        if history_length is None:
            return task
        return {**task, "history": task["history"][-history_length:] if history_length > 0 else []}

    @router.get("/.well-known/agent-card.json", include_in_schema=False)
    async def card(request: Request):
        return JSONResponse(agent_card(str(request.base_url).rstrip("/"), bool(token)))

    @router.post("/a2a", include_in_schema=False)
    async def rpc(request: Request):
        version = request.headers.get("A2A-Version")
        if version is not None and version.strip() not in SUPPORTED_VERSIONS:
            return JSONResponse({"type": "version-not-supported", "title": "A2A version not supported",
                                 "status": 400, "supportedVersions": [PROTOCOL_VERSION]},
                                status_code=400, media_type="application/problem+json")
        if token:
            auth = request.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], token)):
                return JSONResponse({"detail": "Invalid API token"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
        try:
            body = await request.json()
        except ValueError:
            return rpc_error(None, PARSE_ERROR, "Invalid JSON")
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return rpc_error(body.get("id") if isinstance(body, dict) else None, INVALID_REQUEST,
                             "Expected a JSON-RPC 2.0 request")
        request_id, method, params = body.get("id"), body["method"], body.get("params") or {}
        if not isinstance(params, dict):
            return rpc_error(request_id, INVALID_PARAMS, "params must be an object")

        if method == "GetTask":
            task = tasks.get(params.get("id", ""))
            if task is None:
                return rpc_error(request_id, TASK_NOT_FOUND, "Task not found")
            history_length = params.get("historyLength")
            if history_length is not None and (not isinstance(history_length, int) or history_length < 0):
                return rpc_error(request_id, INVALID_PARAMS, "historyLength must be a non-negative integer")
            return rpc_result(request_id, trimmed(task, history_length))

        if method in KNOWN_UNSUPPORTED:
            return rpc_error(request_id, UNSUPPORTED_OPERATION, f"{method} is not supported by this agent")
        if method != "SendMessage":
            return rpc_error(request_id, METHOD_NOT_FOUND, f"Unknown method {method}")

        message = params.get("message")
        text, problem = message_text(message)
        if problem:
            return rpc_error(request_id, INVALID_PARAMS, problem)
        config = params.get("configuration") or {}
        accepted = config.get("acceptedOutputModes")
        if accepted and not ({"text/plain", "application/json"} & set(accepted)):
            return rpc_error(request_id, CONTENT_TYPE_NOT_SUPPORTED, "TravelMate answers in text/plain")
        previous = tasks.get(message.get("taskId") or "")
        if message.get("taskId") and previous is None:
            return rpc_error(request_id, TASK_NOT_FOUND, "Task not found")
        # A message for an input-required task continues it; otherwise a new task starts.
        continuing = previous is not None and previous["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
        if previous is not None and not continuing:
            return rpc_error(request_id, INVALID_PARAMS, "That task is already finished; send without taskId")
        context_id = message.get("contextId") or (previous or {}).get("contextId")
        try:
            session, replies = await chat.handle_turn(context_id, text)
            reply = replies[-1] if len(replies) > 1 else replies[0]
            if len(replies) > 1:  # several things asked: one text answer, every artifact
                reply = reply.model_copy(update={
                    "text": PARAGRAPH.join(r.text for r in replies),
                    "places": [p for r in replies for p in r.places],
                    "citations": [c for r in replies for c in r.citations],
                    "plan": next((r.plan for r in replies if r.plan is not None), None),
                    "failed": all(r.failed for r in replies),
                    "agent": "+".join(r.agent or "" for r in replies),
                })
        except Exception as exc:
            logger.warning("a2a outcome=failed error_type=%s", type(exc).__name__)
            return rpc_error(request_id, INTERNAL_ERROR, "TravelMate could not handle the message; retry shortly")
        task_id = previous["id"] if continuing else str(uuid.uuid4())
        user = {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": message["messageId"],
                "contextId": session.id, "taskId": task_id}
        agent = {"role": "ROLE_AGENT", "parts": [{"text": reply.text}], "messageId": str(uuid.uuid4()),
                 "contextId": session.id, "taskId": task_id,
                 "metadata": {"specialist": reply.agent, "reason": reply.reason}}
        task = {
            "id": task_id,
            "contextId": session.id,
            "status": {"state": task_state(reply),
                       "message": agent, "timestamp": now()},
            "artifacts": ((previous or {}).get("artifacts") or []) + artifacts_for(reply),
            "history": ((previous or {}).get("history") or []) + [user, agent],
            "metadata": {"specialist": reply.agent},
        }
        keep(task)
        history_length = config.get("historyLength")
        return rpc_result(request_id, {"task": trimmed(task, history_length if isinstance(history_length, int)
                                                       and history_length >= 0 else None)})

    return router
