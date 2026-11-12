"""Product API: accounts, saved trips (with editing), favourites, place pages, reviews and admin.

Signed-in users send `Authorization: Bearer <session token>`. The same header also unlocks the
planning API, so a signed-in user does not need the operator's TRAVELMATE_API_TOKEN.
"""

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, ValidationError, field_validator, model_validator

from app.agents.budget import BudgetAgent
from app.agents.rule_scheduler import rule_draft
from app.agents.self_check import review_draft
from app.core.models import (
    BudgetInput,
    Context,
    Draft,
    Model,
    Place,
    PlaceResult,
    SelfCheckReport,
    SelfCheckRound,
    TravelStyle,
    TripRequest,
    UserCost,
    WeatherResult,
)
from app.memory.store import StoreError

logger = logging.getLogger(__name__)
SESSION_COOKIE = "tm_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def session_from(request, credentials, store):
    """(user, token) from a Bearer session token or the HttpOnly session cookie, else (None, None).

    Cookie-authenticated writes must carry the X-Requested-With: travelmate header. Another site
    cannot add a custom header to a cross-site request without CORS (not enabled), and the cookie
    is SameSite=Strict as well, so a forged form post cannot act as the user (CSRF).
    """
    if credentials is not None:
        user = await asyncio.to_thread(store.user_for_token, credentials.credentials)
        if user is not None:
            return user, credentials.credentials
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None, None
    if request.method not in SAFE_METHODS and request.headers.get("X-Requested-With") != "travelmate":
        return None, None
    user = await asyncio.to_thread(store.user_for_token, token)
    return (user, token) if user else (None, None)


def set_session_cookie(response, request, token):
    response.set_cookie(SESSION_COOKIE, token, max_age=30 * 24 * 3600, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")


EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
LOGIN_WINDOW_S, LOGIN_ATTEMPTS = 15 * 60, 8
CONTACT_WINDOW_S, CONTACT_MESSAGES = 60 * 60, 5
CONTACT_TOPICS = ("support", "feedback", "partner", "privacy", "other")


class Credentials(Model):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not EMAIL.match(value.strip()):
            raise ValueError("Email không hợp lệ")
        return value.strip()


class Signup(Credentials):
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class ContactMessage(Model):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254)
    topic: Literal[CONTACT_TOPICS] = "other"
    message: str = Field(min_length=10, max_length=4000)
    # Honeypot: hidden from people, filled in by bots. A message that has it is dropped quietly.
    website: str = Field(default="", max_length=200)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not EMAIL.match(value.strip()):
            raise ValueError("Email không hợp lệ")
        return value.strip()


class MessageUpdate(Model):
    status: Literal["new", "done"]


class Forgot(Model):
    email: str = Field(max_length=254)


class Reset(Model):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class ProfileUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    interests: list[str] | None = Field(default=None, max_length=10)

    @field_validator("interests")
    @classmethod
    def short_interests(cls, value):
        if value is not None and any(not 0 < len(v.strip()) <= 40 for v in value):
            raise ValueError("Mỗi sở thích dài 1–40 ký tự")
        return None if value is None else [v.strip() for v in value]


class PasswordChange(Model):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountDelete(Model):
    password: str = Field(min_length=1, max_length=128)


class TripSave(Model):
    request: dict
    result: dict
    title: str | None = Field(default=None, max_length=120)


class TripEdit(Model):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    draft: Draft | None = None
    # Favourite places the user added to the schedule; must already be in their favourites.
    added_place_ids: list[str] = Field(default_factory=list, max_length=20)
    # Move the whole trip to a new first day (same length, same schedule).
    start_date: date | None = None
    # Let the rule-based scheduler rearrange every day from the trip's places.
    auto_arrange: bool = False
    # Costs the user knows (hotel booked, food budget…); replace the previous list when given.
    user_costs: list[UserCost] | None = Field(default=None, max_length=10)
    # Spending level for the reference lodging/food/transport costs.
    travel_style: TravelStyle | None = None

    @model_validator(mode="after")
    def one_schedule_change(self):
        if sum([self.draft is not None, self.start_date is not None, self.auto_arrange]) > 1:
            raise ValueError("Mỗi lần chỉ sửa lịch, đổi ngày hoặc xếp lại tự động.")
        return self


class ReviewIn(Model):
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=10, max_length=1000)


class ReportIn(Model):
    reason: str = Field(min_length=3, max_length=300)


class UserAdminUpdate(Model):
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "locked"] | None = None


class PlaceAdminUpdate(Model):
    hidden: bool | None = None
    admin_note: str | None = Field(default=None, max_length=500)


class Moderation(Model):
    action: Literal["approve", "reject", "hide"]
    note: str = Field(default="", max_length=300)


def trip_for(request):
    """A saved trip may be in the past now: build it without the "not in the past" rule."""
    return TripRequest.model_construct(**{**request, "start_date": date.fromisoformat(request["start_date"]),
                                          "end_date": date.fromisoformat(request["end_date"]),
                                          "budget_vnd": Decimal(str(request["budget_vnd"])),
                                          "travelers": int(request["travelers"])})


def edited_result(request, result, draft, extra_places):
    """Validate an edited schedule against the saved trip and recompute its budget."""
    plan_days = [d["date"] for d in result["draft"]["days"]]
    if [d.date.isoformat() for d in draft.days] != plan_days:
        raise StoreError("Không được thêm, bớt hay đổi ngày của chuyến đi; chỉ sửa hoạt động trong từng ngày.")
    places = {p["id"]: p for p in result["places"]}
    for place in extra_places:
        places.setdefault(place["id"], place)
    for day in draft.days:
        last_end = -1
        seen = set()
        for activity in sorted(day.activities, key=lambda a: a.start_minute):
            if activity.place_id not in places:
                raise StoreError("Lịch có địa điểm không thuộc chuyến đi hay danh sách yêu thích.")
            if activity.start_minute < last_end:
                raise StoreError(f"Ngày {day.date:%d/%m}: các hoạt động bị chồng giờ.")
            if activity.place_id in seen:
                raise StoreError(f"Ngày {day.date:%d/%m}: một địa điểm xuất hiện hai lần.")
            seen.add(activity.place_id)
            last_end = activity.end_minute
        day.activities.sort(key=lambda a: a.start_minute)
    used = {a.place_id for d in draft.days for a in d.activities}
    kept = [Place.model_validate(p) for pid, p in places.items() if pid in used or pid in {x["id"] for x in result["places"]}]
    data = BudgetInput.model_construct(trip=trip_for(request), draft=draft, places=PlaceResult(places=kept))
    return data, kept


def create_accounts_router(store, settings, mailer=None):
    router = APIRouter(prefix="/api/v1")
    if mailer is None:
        from app.trust.mailer import Mailer

        mailer = Mailer(getattr(settings, "travelmate_smtp_host", ""), getattr(settings, "travelmate_smtp_port", 587),
                        getattr(settings, "travelmate_smtp_user", ""), getattr(settings, "travelmate_smtp_password", ""),
                        getattr(settings, "travelmate_smtp_from", ""))
    bearer = HTTPBearer(auto_error=False)
    attempts: dict[str, deque] = defaultdict(deque)
    contact_attempts: dict[str, deque] = defaultdict(deque)

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    async def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        user, token = await session_from(request, credentials, store)
        if user is None:
            raise HTTPException(401, "Bạn cần đăng nhập, hoặc phiên đăng nhập đã hết hạn.")
        return {**user, "token": token}

    async def optional_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        user, _ = await session_from(request, credentials, store)
        return user

    async def admin_user(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "Chỉ quản trị viên mới dùng được chức năng này.")
        return user

    def throttle(request, email):
        key = f"{request.client.host if request.client else '-'}|{email.casefold()}"
        window = attempts[key]
        now = time.monotonic()
        while window and now - window[0] > LOGIN_WINDOW_S:
            window.popleft()
        if len(window) >= LOGIN_ATTEMPTS:
            raise HTTPException(429, "Bạn đã thử quá nhiều lần. Vui lòng đợi 15 phút.", headers={"Retry-After": "900"})
        window.append(now)

    def reset_link(request, token):
        base = getattr(settings, "travelmate_public_url", "") or str(request.base_url)
        return f"{base.rstrip('/')}/?view=forgot&reset={token}"

    # --- accounts ------------------------------------------------------------------------

    @router.post("/auth/signup")
    async def signup(data: Signup, request: Request, response: Response):
        if not settings.travelmate_signup_open:
            raise HTTPException(403, "Đăng ký đang tạm đóng.")
        throttle(request, data.email)
        token, user = await run(store.signup, data.email, data.password, data.name)
        set_session_cookie(response, request, token)
        return {"token": token, "user": user}

    @router.post("/auth/login")
    async def login(data: Credentials, request: Request, response: Response):
        throttle(request, data.email)
        token, user = await run(store.login, data.email, data.password)
        set_session_cookie(response, request, token)
        return {"token": token, "user": user}

    @router.post("/auth/logout")
    async def logout(response: Response, user=Depends(current_user)):
        await run(store.logout, user["token"])
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.post("/auth/forgot")
    async def forgot(data: Forgot, request: Request):
        throttle(request, data.email)
        user, token = await run(store.create_reset, email=data.email)
        if token and mailer.enabled:
            try:
                await asyncio.to_thread(mailer.send_reset, user["email"], user["name"], reset_link(request, token))
            except Exception as exc:  # never reveal to the caller whether the email exists or failed
                logger.warning("password_reset email outcome=failed error_type=%s", type(exc).__name__)
        elif token:
            # No email service configured: the operator reads the link from the server log.
            logger.warning("password_reset user=%s link=%s (valid 30 minutes)", user["id"], reset_link(request, token))
        if mailer.enabled:
            return {"ok": True, "message": "Nếu email có tài khoản, chúng tôi đã gửi link đặt lại mật khẩu (hiệu lực 30 "
                                           "phút). Kiểm tra cả thư mục spam."}
        return {"ok": True, "message": "Nếu email có tài khoản, link đặt lại mật khẩu đã được tạo (hiệu lực 30 phút). "
                                       "Máy chủ chưa cấu hình gửi email: quản trị viên lấy link trong log máy chủ hoặc "
                                       "cấp lại trong trang Quản trị."}

    @router.post("/auth/reset")
    async def reset(data: Reset):
        await run(store.reset_password, data.token, data.password)
        return {"ok": True}

    @router.get("/me")
    async def me(user=Depends(current_user)):
        return {k: v for k, v in user.items() if k != "token"}

    @router.patch("/me")
    async def update_me(data: ProfileUpdate, user=Depends(current_user)):
        return await run(store.update_profile, user["id"], data.name, data.interests)

    @router.post("/me/password")
    async def change_password(data: PasswordChange, user=Depends(current_user)):
        await run(store.change_password, user["id"], data.current_password, data.new_password, user["token"])
        return {"ok": True}

    @router.post("/me/delete")
    async def delete_me(data: AccountDelete, response: Response, user=Depends(current_user)):
        await run(store.delete_account, user["id"], data.password)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    # --- trips ---------------------------------------------------------------------------

    @router.get("/me/trips")
    async def my_trips(user=Depends(current_user)):
        return await run(store.trips, user["id"])

    @router.post("/me/trips")
    async def save_trip(data: TripSave, user=Depends(current_user)):
        try:
            from app.core.models import PlanResponse

            plan = PlanResponse.model_validate(data.result)
            for key in ("destination", "start_date", "end_date", "travelers", "budget_vnd"):
                if key not in data.request:
                    raise ValueError(key)
        except (ValidationError, ValueError):
            raise HTTPException(422, "Dữ liệu chuyến đi không hợp lệ.") from None
        await run(store.remember_places, [p.model_dump(mode="json") for p in plan.places + plan.stays])
        title = data.title or f"{data.request['destination']} · {len(plan.draft.days)} ngày"
        return await run(store.save_trip, user["id"], data.request, plan.model_dump(mode="json"), title)

    @router.get("/me/trips/{trip_id}")
    async def get_trip(trip_id: str, user=Depends(current_user)):
        return await run(store.trip, user["id"], trip_id)

    @router.patch("/me/trips/{trip_id}")
    async def edit_trip(trip_id: str, data: TripEdit, user=Depends(current_user)):
        changes_plan = (data.draft is not None or data.start_date or data.auto_arrange or data.user_costs is not None
                        or data.travel_style is not None)
        if not changes_plan:
            return await run(store.update_trip, user["id"], trip_id, data.title)
        trip = await run(store.trip, user["id"], trip_id)
        request, result = dict(trip["request"]), dict(trip["result"])
        if data.travel_style is not None:
            request["travel_style"] = data.travel_style
        draft = data.draft or Draft.model_validate(result["draft"])
        weather = WeatherResult.model_validate(result.get("weather") or {})
        scheduled_by = "manual"
        if data.start_date is not None:
            if data.start_date < date.today():
                raise HTTPException(400, "Ngày đi mới không được ở quá khứ.")
            shift = data.start_date - date.fromisoformat(request["start_date"])
            request["start_date"] = data.start_date.isoformat()
            request["end_date"] = (date.fromisoformat(request["end_date"]) + shift).isoformat()
            for day in draft.days:
                day.date = day.date + shift
            result["draft"] = draft.model_dump(mode="json")
            # The old forecast belongs to the old dates.
            weather = WeatherResult(warnings=["Đã đổi ngày đi: dự báo cũ không còn đúng; tạo lại lịch để có dự báo mới."])
            result["weather"] = weather.model_dump(mode="json")
        favorites = {p["id"]: p for p in await run(store.favorites, user["id"])}
        if any(pid not in favorites for pid in data.added_place_ids):
            raise HTTPException(400, "Chỉ thêm được địa điểm trong danh sách yêu thích.")
        if data.auto_arrange:
            trip_model = trip_for(request)
            draft = rule_draft(trip_model, PlaceResult(places=[Place.model_validate(p) for p in result["places"]]),
                               weather)
            scheduled_by = "rules"
        try:
            budget_input, kept = edited_result(request, result, draft, [favorites[p] for p in data.added_place_ids])
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        costs = data.user_costs if data.user_costs is not None else [
            UserCost.model_validate(c) for c in result.get("user_costs", [])]
        # The user's own costs replace the reference estimate for their category.
        budget = await BudgetAgent().execute(budget_input.model_copy(update={"user_costs": costs}), Context())
        # Self-check the edited schedule with the same rules the AI planner is held to.
        checks = review_draft(draft, PlaceResult(places=kept), weather)
        report = SelfCheckReport(rounds=[SelfCheckRound(round=1, checks=checks)], final_passed=all(c.passed for c in checks),
                                 scheduled_by=scheduled_by)
        result.update(draft=draft.model_dump(mode="json"), places=[p.model_dump(mode="json") for p in kept],
                      budget=budget.model_dump(mode="json"), self_check=report.model_dump(mode="json"), edited=True,
                      user_costs=[c.model_dump() for c in costs])
        return await run(store.update_trip, user["id"], trip_id, data.title, result, request)

    @router.delete("/me/trips/{trip_id}")
    async def delete_trip(trip_id: str, user=Depends(current_user)):
        await run(store.delete_trip, user["id"], trip_id)
        return {"ok": True}

    # --- chats -----------------------------------------------------------------------------

    @router.get("/me/chats")
    async def my_chats(user=Depends(current_user)):
        return await run(store.chats, user["id"])

    @router.get("/me/chats/{chat_id}")
    async def get_chat(chat_id: str, user=Depends(current_user)):
        chat = await run(store.chat, user["id"], chat_id)
        state = chat["state"]
        return {"id": chat["id"], "title": chat["title"], "messages": state.get("messages", []),
                "active_agent": state.get("active_agent")}

    @router.delete("/me/chats/{chat_id}")
    async def delete_chat(chat_id: str, user=Depends(current_user)):
        await run(store.delete_chat, user["id"], chat_id)
        return {"ok": True}

    # --- favourites and place pages -------------------------------------------------------

    @router.get("/me/favorites")
    async def favorites(user=Depends(current_user)):
        return await run(store.favorites, user["id"])

    @router.put("/me/favorites/{place_id}")
    async def add_favorite(place_id: str, user=Depends(current_user)):
        await run(store.set_favorite, user["id"], place_id, True)
        return {"ok": True}

    @router.delete("/me/favorites/{place_id}")
    async def remove_favorite(place_id: str, user=Depends(current_user)):
        await run(store.set_favorite, user["id"], place_id, False)
        return {"ok": True}

    @router.get("/places/{place_id}")
    async def place_page(place_id: str, user=Depends(optional_user)):
        return await run(store.place, place_id, user)

    # --- reviews -------------------------------------------------------------------------

    @router.get("/me/reviews")
    async def my_reviews(user=Depends(current_user)):
        return await run(store.my_reviews, user["id"])

    @router.put("/places/{place_id}/review")
    async def write_review(place_id: str, data: ReviewIn, user=Depends(current_user)):
        return await run(store.upsert_review, user["id"], place_id, data.rating, data.text)

    @router.delete("/places/{place_id}/review")
    async def delete_review(place_id: str, user=Depends(current_user)):
        await run(store.delete_review, user["id"], place_id)
        return {"ok": True}

    @router.post("/reviews/{review_id}/report")
    async def report(review_id: str, data: ReportIn, user=Depends(current_user)):
        await run(store.report_review, user["id"], review_id, data.reason)
        return {"ok": True}

    # --- admin ---------------------------------------------------------------------------

    @router.get("/admin/stats")
    async def stats(admin=Depends(admin_user)):
        return await run(store.stats)

    @router.get("/admin/users")
    async def users(q: str = "", admin=Depends(admin_user)):
        return await run(store.users, q[:100])

    @router.patch("/admin/users/{user_id}")
    async def update_user(user_id: str, data: UserAdminUpdate, admin=Depends(admin_user)):
        return await run(store.admin_update_user, admin["id"], user_id, data.role, data.status)

    @router.post("/admin/users/{user_id}/reset-link")
    async def admin_reset_link(user_id: str, request: Request, admin=Depends(admin_user)):
        user, token = await run(store.create_reset, user_id=user_id, actor_id=admin["id"])
        if token is None:
            raise HTTPException(404, "Không tìm thấy người dùng.")
        return {"link": reset_link(request, token), "expires_in_minutes": 30}

    @router.get("/admin/places")
    async def admin_places(q: str = "", hidden: bool | None = None, admin=Depends(admin_user)):
        return await run(store.admin_places, q[:100], hidden)

    @router.patch("/admin/places/{place_id}")
    async def update_place(place_id: str, data: PlaceAdminUpdate, admin=Depends(admin_user)):
        return await run(store.admin_update_place, admin["id"], place_id, data.hidden, data.admin_note)

    @router.get("/admin/moderation")
    async def moderation(admin=Depends(admin_user)):
        return await run(store.moderation_queue)

    @router.post("/admin/reviews/{review_id}/moderate")
    async def moderate(review_id: str, data: Moderation, admin=Depends(admin_user)):
        await run(store.moderate, admin["id"], review_id, data.action, data.note)
        return {"ok": True}

    # --- contact form and its inbox ---------------------------------------------------------

    @router.post("/contact")
    async def contact(data: ContactMessage, request: Request, user=Depends(optional_user)):
        window = contact_attempts[request.client.host if request.client else "-"]
        now = time.monotonic()
        while window and now - window[0] > CONTACT_WINDOW_S:
            window.popleft()
        if len(window) >= CONTACT_MESSAGES:
            raise HTTPException(429, "Bạn đã gửi nhiều tin nhắn trong một giờ. Vui lòng thử lại sau.",
                                headers={"Retry-After": "3600"})
        window.append(now)
        if data.website:
            return {"ok": True}  # a bot filled the hidden field: accept, store nothing
        await run(store.add_message, data.name, data.email, data.topic, data.message, user["id"] if user else None)
        return {"ok": True}

    @router.get("/admin/messages")
    async def admin_messages(status: Literal["new", "done"] | None = None, admin=Depends(admin_user)):
        return await run(store.messages, status)

    @router.patch("/admin/messages/{message_id}")
    async def admin_update_message(message_id: str, data: MessageUpdate, admin=Depends(admin_user)):
        await run(store.update_message, admin["id"], message_id, data.status)
        return {"ok": True}

    @router.delete("/admin/messages/{message_id}")
    async def admin_delete_message(message_id: str, admin=Depends(admin_user)):
        await run(store.delete_message, admin["id"], message_id)
        return {"ok": True}

    return router
