"""POST /api/v1/chat: one turn with the AI assistant (concierge + specialists, app/agents/concierge.py).

A signed-in user's conversation is saved to the database, so it can be reopened later, and
a plan made in the chat is saved to their trips. Anonymous conversations live in memory only.
"""

# Endpoint Trợ lý AI. Mỗi lượt: kiểm tra hạn mức -> nạp hội thoại cũ (nếu có) -> agent trả lời -> lọc địa
# điểm bị ẩn -> lưu hội thoại và lịch trình (nếu đã đăng nhập) -> trừ lượt.

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.concierge import ChatRequest, ChatResponse, ChatSession
from app.api.deps import ApiDeps, Credentials
from app.memory.store import StoreError

logger = logging.getLogger(__name__)


# chat là ChatService (app/agents/concierge.py), giữ các phiên chat trong bộ nhớ.
def create_chat_router(deps: ApiDeps, chat):
    router = APIRouter()
    store = deps.store

    # Sau khi máy chủ khởi động lại, phiên chat chỉ còn trong cơ sở dữ liệu: nạp lại để người dùng chat
    # tiếp.
    async def load_session(owner, session_id):
        """A saved conversation of this user that is not in memory (e.g. after a restart), or None."""
        if not (owner and session_id) or session_id in chat.store.sessions:
            return None
        try:
            saved = await asyncio.to_thread(store.chat, owner, session_id)
            return chat.store.put(ChatSession.load(saved["id"], owner, saved["state"]))
        except StoreError:
            return None  # unknown or someone else's: start a new conversation

    # Tiêu đề hội thoại là câu hỏi đầu tiên (tối đa 80 ký tự).
    async def save(owner, session, replies, first_message):
        """Save the conversation, and a plan made in it to the user's trips; returns that trip's id."""
        title = next((m.text for m in session.messages if m.role == "user"), first_message)[:80]
        await asyncio.to_thread(store.save_chat, owner, session.id, title, session.dump())
        planned = next((r for r in replies if r.plan is not None and r.trip is not None), None)
        if planned is None:
            return None
        saved_trip = await asyncio.to_thread(
            store.save_trip, owner, planned.trip.model_dump(mode="json"), planned.plan.model_dump(mode="json"),
            f"{planned.trip.destination} · {len(planned.plan.draft.days)} ngày (Trợ lý AI)")
        return saved_trip["id"]

    # Một lượt chat. Agent có thể trả về nhiều câu trả lời (ví dụ chuyển từ trợ lý sang chuyên gia).
    @router.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(deps.authorize)])
    async def chat_turn(data: ChatRequest, request: Request, credentials: Credentials):
        charged = await deps.quota_owner(request, credentials, "chat")
        user = await deps.user(request, credentials)
        owner = user["id"] if user else None
        trip_id = None
        try:
            session = await load_session(owner, data.session_id)
            session, replies = await chat.handle_turn(data.session_id, data.message, owner, session)
            for reply in replies:
                if reply.places:
                    reply.places = await deps.visible(reply.places)
                await deps.remember(reply.places + (reply.plan.places + reply.plan.stays if reply.plan else []))
            if owner:
                trip_id = await save(owner, session, replies, data.message)
        except Exception as exc:
            logger.warning("chat outcome=failed error_type=%s", type(exc).__name__)
            raise HTTPException(502, "Chat failed; retry shortly") from None
        await deps.charge(charged, "chat")
        return ChatResponse(session_id=session.id, reply=replies[0], replies=replies,
                            active_agent=session.active_agent, trip_id=trip_id)

    return router
