"""What the API routes share: who is calling, daily AI limits, and recording places.

A caller is one of three: the operator (TRAVELMATE_API_TOKEN, e.g. scripts and the live
check), a signed-in user (session cookie or Bearer session token), or an anonymous visitor
(only allowed when no token is configured, i.e. a local demo).
"""

# Các hàm dùng chung cho mọi endpoint: xác định người gọi, kiểm tra và trừ hạn mức AI, ghi nhận địa điểm đã
# hiển thị cho người dùng.

import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.memory.store import VIETNAM
from app.trust.accounts import session_from

logger = logging.getLogger(__name__)

# Đọc header Authorization: Bearer <token>; không có thì trả None thay vì báo lỗi ngay.
bearer = HTTPBearer(auto_error=False)
# The Bearer token of a request, if any: the operator token or a user's session token.
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]

# Tên hiển thị trong thông báo hết hạn mức.
QUOTA_LABELS = {"plan": "lượt lập lịch trình", "chat": "tin nhắn với Trợ lý AI"}


# Dùng cho header Retry-After khi hết hạn mức.
def seconds_to_midnight_vn():
    """Seconds until the daily limits reset (midnight, Vietnam time)."""
    now = datetime.now(VIETNAM)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds()) + 1


# Chỉ ghi loại lỗi vào log, không ghi nội dung, để không lộ khoá API hay prompt.
def log_plan_failure(event, exc):
    """Log an unexpected planning error by type only.

    Never logs provider URLs containing keys, prompts or stack traces; the type of the error
    and of its root cause is enough to tell a provider outage from a bug.
    """
    root = exc
    # Lần theo chuỗi lỗi đến lỗi gốc (ví dụ lỗi mạng bên trong lỗi agent).
    while root.__cause__ is not None or root.__context__ is not None:
        root = root.__cause__ or root.__context__
    logger.warning("%s outcome=failed error_type=%s root_type=%s", event, type(exc).__name__, type(root).__name__)


# Một đối tượng cho cả ứng dụng, giữ cấu hình và cơ sở dữ liệu.
class ApiDeps:
    """Access checks and bookkeeping used by every router, bound to one settings + store."""

    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    # --- Who is calling --------------------------------------------------------------------

    # compare_digest so sánh mất thời gian như nhau, chống đoán token qua thời gian phản hồi.
    def is_operator(self, credentials):
        token = self.settings.travelmate_api_token
        return bool(credentials is not None and token and secrets.compare_digest(credentials.credentials, token))

    # Dùng làm dependency của FastAPI: chặn yêu cầu không có quyền bằng lỗi 401.
    async def authorize(self, request: Request, credentials: Credentials):
        """Route dependency: the operator token or a signed-in user; anyone when no token is set."""
        if not self.settings.travelmate_api_token or self.is_operator(credentials):
            return
        user, _ = await session_from(request, credentials, self.store)
        if user is None:
            raise HTTPException(401, "Invalid API token")

    # Phiên đăng nhập đọc từ cookie HttpOnly hoặc Bearer token.
    async def user(self, request, credentials):
        """The signed-in user (a dict) or None."""
        user, _ = await session_from(request, credentials, self.store)
        return user

    # Khoá chủ sở hữu job: mỗi người chỉ xem được lịch trình mình tạo.
    async def job_owner(self, request, credentials):
        """(owner key, user) deciding whose plan jobs a request may see."""
        if self.is_operator(credentials):
            return "operator", None
        user = await self.user(request, credentials)
        if user is not None:
            return f"user:{user['id']}", user
        return "public", None

    # --- Daily AI limits -------------------------------------------------------------------

    # 0 nghĩa là không giới hạn.
    def daily_limit(self, kind):
        return {"plan": self.settings.travelmate_daily_plans, "chat": self.settings.travelmate_daily_chats}[kind]

    # Gọi TRƯỚC khi chạy AI để chặn sớm; việc trừ lượt làm SAU khi thành công (charge), nên lỗi không làm
    # mất lượt.
    async def quota_owner(self, request, credentials, kind):
        """The signed-in user to charge for one AI use, or None when nobody is limited.

        Admins, the operator token and visitors on a server without accounts are not limited.
        Raises 429 when today's uses are spent. Uses are counted after success (charge()).
        """
        limit = self.daily_limit(kind)
        if not limit or self.is_operator(credentials):
            return None
        user = await self.user(request, credentials)
        if user is None or user["role"] == "admin":
            return None
        used = (await asyncio.to_thread(self.store.usage_today, user["id"])).get(kind, 0)
        if used >= limit:
            raise HTTPException(
                429, f"Bạn đã dùng hết {limit} {QUOTA_LABELS[kind]} của hôm nay. Hạn mức được làm mới lúc 0 giờ "
                     "(giờ Việt Nam).", headers={"Retry-After": str(seconds_to_midnight_vn())})
        return user["id"]

    # Lỗi khi đếm lượt chỉ ghi log, không làm hỏng yêu cầu đã thành công.
    async def charge(self, owner, kind):
        """Count one AI use for owner (from quota_owner); None means not limited."""
        if owner is None:
            return
        try:
            await asyncio.to_thread(self.store.add_usage, owner, kind)
        except Exception as exc:  # counting must never fail a request that already succeeded
            logger.warning("usage outcome=failed error_type=%s", type(exc).__name__)

    # --- Places ----------------------------------------------------------------------------

    # Lưu địa điểm vào cơ sở dữ liệu để trang địa điểm, yêu thích và đánh giá tìm lại được.
    async def remember(self, places):
        """Keep places users were shown, so place pages, favourites and reviews can find them."""
        try:
            await asyncio.to_thread(self.store.remember_places, [p.model_dump(mode="json") for p in places])
        except Exception as exc:  # the product database must never break planning
            logger.warning("store remember_places outcome=failed error_type=%s", type(exc).__name__)

    # Lọc bỏ địa điểm admin đã ẩn.
    async def visible(self, places):
        """Places minus the ones an admin hid."""
        hidden = await asyncio.to_thread(self.store.hidden_place_ids)
        return [p for p in places if p.id not in hidden]

    # Địa chỉ công khai nếu đã cấu hình, không thì lấy từ yêu cầu.
    def public_base(self, request):
        """The site's public address, for links in the sitemap and share previews."""
        return self.settings.travelmate_public_url or str(request.base_url).rstrip("/")
