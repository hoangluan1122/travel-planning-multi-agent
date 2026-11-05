import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.models import Place, PlaceResult, TicketInfo
from app.providers import DemoProvider
from app.store import Store, check_password, hash_password

PASSWORD = "matkhau-dai-123"


class Provider(DemoProvider):
    """Search returns two real-looking places; planning uses the demo pipeline."""

    async def search(self, trip):
        return await self.search_places(trip)

    async def search_places(self, query):
        ticket = TicketInfo(group_id="hue-tu-duc", label="Vé lăng Tự Đức", adult_vnd=150000,
                            sources=["https://tuoitre.vn/x"], checked=date(2026, 11, 5))
        return PlaceResult(places=[
            Place(id="osm:1", name="Lăng Tự Đức", address="Huế", latitude=16.43, longitude=107.56, source="osm",
                  types=["tomb"], ticket=ticket),
            Place(id="osm:2", name="Chùa Thiên Mụ", address="Huế", latitude=16.45, longitude=107.54, source="osm",
                  types=["temple"]),
        ])


TABLES = "audit, reports, reviews, favorites, places, trips, resets, sessions, users"


@pytest.fixture(params=["sqlite", "postgresql"])
def env(request, tmp_path):
    """Every business test runs on SQLite and, when TRAVELMATE_TEST_DATABASE_URL points to a
    disposable PostgreSQL database, on PostgreSQL too (its tables are dropped first)."""
    if request.param == "sqlite":
        store = Store(tmp_path / "t.sqlite3", admin_email="admin@example.com")
    else:
        url = os.environ.get("TRAVELMATE_TEST_DATABASE_URL", "")
        if not url:
            pytest.skip("Set TRAVELMATE_TEST_DATABASE_URL to a disposable PostgreSQL database")
        psycopg = pytest.importorskip("psycopg")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLES} CASCADE")
        store = Store(url, admin_email="admin@example.com")
        assert store.backend == "postgresql"
    settings = Settings(_env_file=None, travelmate_api_token="operator-token")
    client = TestClient(create_app(settings, provider=Provider(), store=store))
    return client, store


def signup(client, email="an@example.com", name="An"):
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def remember(client, headers):
    assert client.post("/api/v1/places/search", json={"destination": "Huế"}, headers=headers).status_code == 200


def trip_payload():
    start = date.today() + timedelta(days=3)
    return {"destination": "Huế", "start_date": start.isoformat(), "end_date": (start + timedelta(1)).isoformat(),
            "travelers": 2, "budget_vnd": "5000000"}


# --- passwords and accounts ------------------------------------------------------------------


def test_password_hash_is_salted_and_verifiable():
    a, b = hash_password(PASSWORD), hash_password(PASSWORD)
    assert a != b and a.startswith("scrypt$") and PASSWORD not in a
    assert check_password(PASSWORD, a) and not check_password("sai", a) and not check_password(PASSWORD, "rác")


def test_signup_login_logout_and_session_unlocks_the_api(env):
    client, _ = env
    headers, user = signup(client)
    assert user["role"] == "user" and user["email"] == "an@example.com"
    assert client.get("/api/v1/me", headers=headers).json()["name"] == "An"
    # The planning API accepts the session instead of the operator token.
    assert client.post("/api/v1/places/search", json={"destination": "Huế"}, headers=headers).status_code == 200
    assert client.post("/api/v1/places/search", json={"destination": "Huế"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": "AN@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_signup_and_login_errors(env):
    client, _ = env
    signup(client)
    dup = client.post("/api/v1/auth/signup", json={"email": "an@example.com", "password": PASSWORD, "name": "B"})
    assert dup.status_code == 409
    short = client.post("/api/v1/auth/signup", json={"email": "b@example.com", "password": "123", "name": "B"})
    assert short.status_code == 422
    bad = client.post("/api/v1/auth/signup", json={"email": "khong-phai-email", "password": PASSWORD, "name": "B"})
    assert bad.status_code == 422
    wrong = client.post("/api/v1/auth/login", json={"email": "an@example.com", "password": "sai-mat-khau"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ai@example.com", "password": "sai-mat-khau"})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()


def test_login_is_throttled(env):
    client, _ = env
    for _ in range(8):
        client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "sai"})
    assert client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "sai"}).status_code == 429


def test_admin_email_becomes_admin(env):
    client, _ = env
    _, admin = signup(client, "Admin@Example.com", "Quản trị")
    assert admin["role"] == "admin"


def test_forgot_and_reset_password(env):
    client, store = env
    headers, user = signup(client)
    assert client.post("/api/v1/auth/forgot", json={"email": "nobody@example.com"}).json()["ok"] is True
    _, token = store.create_reset(email="an@example.com")
    assert client.post("/api/v1/auth/reset", json={"token": token, "password": "mat-khau-moi-456"}).status_code == 200
    assert client.post("/api/v1/auth/reset", json={"token": token, "password": "mat-khau-moi-789"}).status_code == 400
    assert client.get("/api/v1/me", headers=headers).status_code == 401  # old sessions ended
    assert client.post("/api/v1/auth/login", json={"email": "an@example.com", "password": "mat-khau-moi-456"}).status_code == 200


def test_profile_password_change_and_delete(env):
    client, _ = env
    headers, _ = signup(client)
    other, _ = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={
        "email": "an@example.com", "password": PASSWORD}).json()["token"]}, None
    me = client.patch("/api/v1/me", json={"name": "An Nguyễn", "interests": ["Lăng tẩm", "Ăn chay"]}, headers=headers)
    assert me.json()["interests"] == ["Lăng tẩm", "Ăn chay"]
    wrong = client.post("/api/v1/me/password", json={"current_password": "sai", "new_password": "moi-12345678"},
                        headers=headers)
    assert wrong.status_code == 400
    ok = client.post("/api/v1/me/password", json={"current_password": PASSWORD, "new_password": "moi-12345678"},
                     headers=headers)
    assert ok.status_code == 200
    assert client.get("/api/v1/me", headers=other).status_code == 401  # other devices signed out
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    assert client.post("/api/v1/me/delete", json={"password": "moi-12345678"}, headers=headers).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "an@example.com", "password": "moi-12345678"}).status_code == 401


# --- trips -------------------------------------------------------------------------------------


def make_trip(client, headers):
    request = trip_payload()
    plan = client.post("/api/v1/plans/preview", json=request, headers=headers).json()
    saved = client.post("/api/v1/me/trips", json={"request": request, "result": plan}, headers=headers)
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_trips_are_saved_listed_renamed_and_private(env):
    client, _ = env
    headers, _ = signup(client)
    trip = make_trip(client, headers)
    assert trip["title"] == "Huế · 2 ngày" and len(trip["result"]["draft"]["days"]) == 2
    listed = client.get("/api/v1/me/trips", headers=headers).json()
    assert [t["id"] for t in listed] == [trip["id"]] and "result" not in listed[0]
    renamed = client.patch(f"/api/v1/me/trips/{trip['id']}", json={"title": "Huế mùa mưa"}, headers=headers)
    assert renamed.json()["title"] == "Huế mùa mưa"
    stranger, _ = signup(client, "b@example.com", "B")
    assert client.get(f"/api/v1/me/trips/{trip['id']}", headers=stranger).status_code == 404
    assert client.delete(f"/api/v1/me/trips/{trip['id']}", headers=stranger).status_code == 404
    assert client.delete(f"/api/v1/me/trips/{trip['id']}", headers=headers).status_code == 200
    assert client.get("/api/v1/me/trips", headers=headers).json() == []


def test_saving_rejects_invalid_plans(env):
    client, _ = env
    headers, _ = signup(client)
    bad = client.post("/api/v1/me/trips", json={"request": trip_payload(), "result": {"draft": {}}}, headers=headers)
    assert bad.status_code == 422


def test_editing_a_trip_validates_and_recomputes_the_budget(env):
    client, _ = env
    headers, _ = signup(client)
    remember(client, headers)
    trip = make_trip(client, headers)
    days = trip["result"]["draft"]["days"]
    first = days[0]["activities"][0]
    # Add a favourite (Lăng Tự Đức, 150.000 ₫ ticket) to day 1.
    assert client.put("/api/v1/me/favorites/osm:1", headers=headers).status_code == 200
    other = "osm:2" if first["place_id"] == "osm:1" else "osm:1"
    edited = [{"date": days[0]["date"], "activities": [
        first, {"place_id": other, "start_minute": 900, "end_minute": 1000}]}, days[1]]
    added = [] if other in {p["id"] for p in trip["result"]["places"]} else [other]
    r = client.patch(f"/api/v1/me/trips/{trip['id']}", json={"draft": {"days": edited},
                                                                 "added_place_ids": added}, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["edited"] is True and result["self_check"] is None
    assert float(result["budget"]["known_subtotal"]) == 300000
    assert any(p["id"] == "osm:1" for p in result["places"])


@pytest.mark.parametrize("change,message", [
    (lambda days: days[0].update(date="2001-01-01"), "đổi ngày"),
    (lambda days: days[0]["activities"].append({"place_id": "nowhere", "start_minute": 1300, "end_minute": 1350}),
     "không thuộc"),
    (lambda days: days[0]["activities"].append({**days[0]["activities"][0]}), "chồng giờ"),
])
def test_invalid_edits_are_rejected(env, change, message):
    client, _ = env
    headers, _ = signup(client)
    trip = make_trip(client, headers)
    days = trip["result"]["draft"]["days"]
    change(days)
    r = client.patch(f"/api/v1/me/trips/{trip['id']}", json={"draft": {"days": days}}, headers=headers)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_only_favourites_can_be_added(env):
    client, _ = env
    headers, _ = signup(client)
    remember(client, headers)
    trip = make_trip(client, headers)
    days = trip["result"]["draft"]["days"]
    r = client.patch(f"/api/v1/me/trips/{trip['id']}", json={"draft": {"days": days}, "added_place_ids": ["osm:2"]},
                     headers=headers)
    assert r.status_code == 400


# --- favourites, place pages and reviews ------------------------------------------------------


def test_favourites_and_place_page(env):
    client, _ = env
    headers, _ = signup(client)
    assert client.put("/api/v1/me/favorites/osm:1", headers=headers).status_code == 404  # never seen yet
    remember(client, headers)
    assert client.put("/api/v1/me/favorites/osm:1", headers=headers).status_code == 200
    assert [p["name"] for p in client.get("/api/v1/me/favorites", headers=headers).json()] == ["Lăng Tự Đức"]
    page = client.get("/api/v1/places/osm:1", headers=headers).json()
    assert page["favorite"] is True and float(page["place"]["ticket"]["adult_vnd"]) == 150000
    assert page["average_rating"] is None and page["reviews"] == []
    assert client.delete("/api/v1/me/favorites/osm:1", headers=headers).status_code == 200
    assert client.get("/api/v1/places/osm:404").status_code == 404


def test_review_lifecycle_with_moderation_and_reports(env):
    client, _ = env
    admin, _ = signup(client, "admin@example.com", "Quản trị")
    author, _ = signup(client, "an@example.com", "An")
    reader, _ = signup(client, "binh@example.com", "Bình")
    remember(client, author)
    review = client.put("/api/v1/places/osm:1/review", json={"rating": 5, "text": "Kiến trúc đẹp, yên tĩnh."},
                        headers=author)
    assert review.status_code == 200 and review.json()["status"] == "pending"
    assert client.put("/api/v1/places/osm:1/review", json={"rating": 6, "text": "Quá ngắn"}, headers=author).status_code == 422
    # Pending reviews are visible to their author only.
    assert len(client.get("/api/v1/places/osm:1", headers=author).json()["reviews"]) == 1
    assert client.get("/api/v1/places/osm:1", headers=reader).json()["reviews"] == []
    # Only admins moderate.
    assert client.get("/api/v1/admin/moderation", headers=reader).status_code == 403
    queue = client.get("/api/v1/admin/moderation", headers=admin).json()
    review_id = queue["pending"][0]["id"]
    assert client.post(f"/api/v1/admin/reviews/{review_id}/moderate", json={"action": "approve"}, headers=admin).status_code == 200
    page = client.get("/api/v1/places/osm:1", headers=reader).json()
    assert page["average_rating"] == 5 and page["reviews"][0]["author"] == "An"
    # Reports: not your own review, once per user, then the admin hides it.
    assert client.post(f"/api/v1/reviews/{review_id}/report", json={"reason": "spam"}, headers=author).status_code == 400
    assert client.post(f"/api/v1/reviews/{review_id}/report", json={"reason": "spam"}, headers=reader).status_code == 200
    assert client.post(f"/api/v1/reviews/{review_id}/report", json={"reason": "spam"}, headers=reader).status_code == 409
    reported = client.get("/api/v1/admin/moderation", headers=admin).json()["reported"]
    assert reported[0]["report_count"] == 1 and "spam" in reported[0]["reasons"]
    client.post(f"/api/v1/admin/reviews/{review_id}/moderate", json={"action": "hide", "note": "Nội dung spam"},
                headers=admin)
    assert client.get("/api/v1/places/osm:1", headers=reader).json()["reviews"] == []
    mine = client.get("/api/v1/me/reviews", headers=author).json()[0]
    assert mine["status"] == "hidden" and mine["moderation_note"] == "Nội dung spam"
    # Editing a review sends it back to moderation.
    client.put("/api/v1/places/osm:1/review", json={"rating": 4, "text": "Sửa lại: vẫn rất đẹp."}, headers=author)
    assert client.get("/api/v1/me/reviews", headers=author).json()[0]["status"] == "pending"


# --- admin -------------------------------------------------------------------------------------


def test_admin_users_lock_role_and_reset_link(env):
    client, _ = env
    admin, admin_user = signup(client, "admin@example.com", "Quản trị")
    member, member_user = signup(client)
    assert client.get("/api/v1/admin/users", headers=member).status_code == 403
    users = client.get("/api/v1/admin/users?q=an@", headers=admin).json()
    assert [u["email"] for u in users] == ["an@example.com"]
    locked = client.patch(f"/api/v1/admin/users/{member_user['id']}", json={"status": "locked"}, headers=admin)
    assert locked.json()["status"] == "locked"
    assert client.get("/api/v1/me", headers=member).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "an@example.com", "password": PASSWORD}).status_code == 403
    assert client.patch(f"/api/v1/admin/users/{admin_user['id']}", json={"role": "user"}, headers=admin).status_code == 400
    link = client.post(f"/api/v1/admin/users/{member_user['id']}/reset-link", headers=admin).json()
    assert "view=forgot&reset=" in link["link"]
    stats = client.get("/api/v1/admin/stats", headers=admin).json()
    assert stats["users"] == 2 and stats["locked_users"] == 1 and stats["recent"]


def test_hidden_places_disappear_for_users(env):
    client, _ = env
    admin, _ = signup(client, "admin@example.com", "Quản trị")
    member, _ = signup(client)
    remember(client, member)
    client.put("/api/v1/me/favorites/osm:2", headers=member)
    r = client.patch("/api/v1/admin/places/osm:2", json={"hidden": True, "admin_note": "Đang trùng tu"}, headers=admin)
    assert r.json()["hidden"] is True and r.json()["admin_note"] == "Đang trùng tu"
    found = client.post("/api/v1/places/search", json={"destination": "Huế"}, headers=member).json()["places"]
    assert [p["id"] for p in found] == ["osm:1"]
    assert client.get("/api/v1/places/osm:2", headers=member).status_code == 404
    assert client.get("/api/v1/places/osm:2", headers=admin).status_code == 200
    assert client.get("/api/v1/me/favorites", headers=member).json() == []
    places = client.get("/api/v1/admin/places?hidden=true", headers=admin).json()
    assert [p["place"]["id"] for p in places] == ["osm:2"]


def test_hidden_places_never_reach_ai_plans(env):
    client, store = env
    admin, _ = signup(client, "admin@example.com", "Quản trị")
    member, _ = signup(client)
    remember(client, member)
    client.patch("/api/v1/admin/places/osm:1", json={"hidden": True}, headers=admin)
    plan = client.post("/api/v1/plans/preview", json=trip_payload(), headers=member).json()
    assert "osm:1" not in {p["id"] for p in plan["places"]}
    scheduled = {a["place_id"] for d in plan["draft"]["days"] for a in d["activities"]}
    assert "osm:1" not in scheduled
