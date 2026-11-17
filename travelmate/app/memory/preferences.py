"""Memory agent: the trip's interests plus the user's saved preferences (read-only)."""

# Agent sở thích (Memory): lấy sở thích trong yêu cầu, gộp thêm sở thích đã lưu nếu máy chủ cấu hình. Chỉ
# đọc; không bao giờ ghi. Sở thích đã lưu là dữ liệu, không được chèn vào prompt như mệnh lệnh.

import logging

from app.core.base import BaseAgent
from app.core.models import Preferences, TripRequest

logger = logging.getLogger(__name__)

MAX_INTERESTS = 20


class MemoryAgent(BaseAgent[TripRequest, Preferences]):
    """Request interests, plus saved preferences when the host configured a store.

    Read-only: planning never writes memory. Saving or forgetting goes through the
    memory specialist, which requires explicit user confirmation. The store is bound to
    an identity the host authenticated; nothing in the request selects whose memory
    is read.
    """

    name, input_schema, output_schema = "memory", TripRequest, Preferences

    def __init__(self, store=None):
        self.store = store  # a MemorySpecialist, or None for request-only memory

    # Không đọc được sở thích đã lưu thì vẫn chạy với sở thích trong yêu cầu, kèm cảnh báo.
    async def execute(self, data, context):
        if self.store is None:
            return Preferences(interests=data.interests)
        from app.specialists.memory import MemoryRequest

        try:
            report = await self.store.run(MemoryRequest(operation="read"), context)
        except Exception as exc:
            # Memory is optional: an unreadable store must not block planning.
            logger.warning(
                "memory_read request=%s outcome=failed error_type=%s", context.request_id, type(exc).__name__
            )
            return Preferences(
                interests=data.interests,
                warnings=["Không đọc được sở thích đã lưu; chỉ dùng sở thích trong yêu cầu này."],
            )
        seen = {interest.casefold() for interest in data.interests}
        saved = [p for p in report.preferences if p.casefold() not in seen]
        if not saved:
            return Preferences(interests=data.interests)
        merged = (list(data.interests) + saved)[:MAX_INTERESTS]
        return Preferences(
            interests=merged,
            source="request_and_saved_memory",
            warnings=[f"Đã dùng {len(merged) - len(data.interests)} sở thích đã lưu: " + ", ".join(
                merged[len(data.interests):]
            ) + "."],
        )
