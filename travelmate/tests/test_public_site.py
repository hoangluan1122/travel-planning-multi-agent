"""The public, commercial site: pages at /, SEO files, security headers, daily AI quotas, contact form."""

import pytest
from fastapi.testclient import TestClient
from test_accounts import PASSWORD, Provider, signup, trip_payload

from app.core.base import AgentError
from app.main import Settings, create_app
from app.memory.store import Store


def make(tmp_path, orchestrator=None, **overrides):
    store = Store(tmp_path / "site.sqlite3", admin_email="admin@example.com")
    settings = Settings(_env_file=None, travelmate_api_token="operator-token", **overrides)
    return TestClient(create_app(settings, orchestrator=orchestrator, provider=Provider(), store=store)), store


@pytest.fixture
def client(tmp_path):
    return make(tmp_path, travelmate_public_url="https://travelmate.example.vn/")[0]


# --- pages and search engines ------------------------------------------------------------------


def test_home_is_served_at_the_root_with_share_preview(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    page = r.text
    assert '<link rel="canonical" href="https://travelmate.example.vn/">' in page
    assert 'property="og:image" content="https://travelmate.example.vn/ui/travelmate-ui/assets/beach.jpg"' in page
    assert 'src="/ui/travelmate-v2/site.js"' in page and 'href="/ui/travelmate-v2/style.css"' in page
    assert "noindex" not in page


def test_each_public_page_has_its_own_title_and_private_pages_are_not_indexed(client):
    pricing = client.get("/?view=pricing").text
    assert "<title>Bảng giá — TravelMate</title>" in pricing
    assert '<link rel="canonical" href="https://travelmate.example.vn/?view=pricing">' in pricing
    assert pricing.count("<title>") == 1 and pricing.count('name="description"') == 1
    saved = client.get("/?view=saved").text
    assert '<meta name="robots" content="noindex">' in saved and "canonical" not in saved


def test_old_address_redirects_to_the_root_keeping_the_page(client):
    r = client.get("/ui/travelmate-v2/index.html?view=plan&id=abc", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/?view=plan&id=abc"
    assert client.get("/ui/travelmate-v2/index.html", follow_redirects=False).headers["location"] == "/"


def test_robots_and_sitemap_point_at_the_public_address(client):
    robots = client.get("/robots.txt").text
    assert "Disallow: /api/" in robots and "Sitemap: https://travelmate.example.vn/sitemap.xml" in robots
    sitemap = client.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    for loc in ("https://travelmate.example.vn/</loc>", "?view=privacy</loc>", "?view=terms</loc>", "?view=contact</loc>"):
        assert loc in sitemap.text
    assert "view=saved" not in sitemap.text


def test_security_headers_on_pages_and_api(client):
    for path in ("/", "/health", "/ui/travelmate-v2/site.js"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert client.get("/ui/travelmate-v2/site.js").headers["cache-control"] == "no-cache"


def test_public_url_must_be_a_web_address():
    with pytest.raises(ValueError):
        Settings(_env_file=None, travelmate_public_url="travelmate.vn")


def test_site_info_for_the_legal_pages(tmp_path):
    c, _ = make(tmp_path, travelmate_operator_name="Công ty ABC", travelmate_contact_email="hotro@abc.vn",
                travelmate_daily_plans=5)
    assert c.get("/api/v1/site").json() == {"operator_name": "Công ty ABC", "contact_email": "hotro@abc.vn",
                                            "daily_plans": 5, "daily_chats": 60, "signup_open": True}


# --- daily AI quotas -----------------------------------------------------------------------------


def test_plans_are_limited_per_user_per_day(tmp_path):
    c, _ = make(tmp_path, travelmate_daily_plans=2)
    headers, _ = signup(c)
    for _ in range(2):
        assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=headers).status_code == 200
    over = c.post("/api/v1/plans/preview", json=trip_payload(), headers=headers)
    assert over.status_code == 429 and "hết 2 lượt lập lịch" in over.json()["detail"]
    assert 0 < int(over.headers["retry-after"]) <= 24 * 3600 + 1
    assert c.get("/api/v1/me/usage", headers=headers).json()["plan"] == {"used": 2, "limit": 2}
    # Someone else still has their own quota; the operator token and admins have none.
    other, _ = signup(c, "binh@example.com", "Bình")
    assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=other).status_code == 200
    operator = {"Authorization": "Bearer operator-token"}
    assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=operator).status_code == 200
    admin, _ = signup(c, "admin@example.com", "Quản trị")
    for _ in range(3):
        assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=admin).status_code == 200
    assert c.get("/api/v1/me/usage", headers=admin).json()["plan"]["limit"] is None


def test_a_failed_plan_is_not_counted(tmp_path):
    class Failing:
        async def plan(self, trip):
            raise AgentError("Gemini quota exhausted")

    c, _ = make(tmp_path, orchestrator=Failing(), travelmate_daily_plans=1)
    headers, _ = signup(c)
    assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=headers).status_code == 502
    assert c.get("/api/v1/me/usage", headers=headers).json()["plan"]["used"] == 0


def test_chat_messages_are_limited(tmp_path):
    c, _ = make(tmp_path, travelmate_daily_chats=1)
    headers, _ = signup(c)
    assert c.post("/api/v1/chat", json={"message": "Tìm quán chay ở Huế"}, headers=headers).status_code == 200
    over = c.post("/api/v1/chat", json={"message": "Còn quán nào nữa?"}, headers=headers)
    assert over.status_code == 429 and "tin nhắn với Trợ lý AI" in over.json()["detail"]


def test_zero_means_no_limit(tmp_path):
    c, _ = make(tmp_path, travelmate_daily_plans=0)
    headers, _ = signup(c)
    for _ in range(3):
        assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=headers).status_code == 200
    assert c.get("/api/v1/me/usage", headers=headers).json()["plan"] == {"used": 0, "limit": None}


# --- contact form ---------------------------------------------------------------------------------

MESSAGE = {"name": "Chi", "email": "chi@example.com", "topic": "partner", "message": "Muốn hợp tác với TravelMate."}


def test_contact_message_reaches_the_admin_inbox(tmp_path):
    c, _ = make(tmp_path)
    assert c.post("/api/v1/contact", json=MESSAGE).json() == {"ok": True}  # no account needed
    user, _ = signup(c)
    assert c.get("/api/v1/admin/messages", headers=user).status_code == 403
    admin, _ = signup(c, "admin@example.com", "Quản trị")
    inbox = c.get("/api/v1/admin/messages?status=new", headers=admin).json()
    assert [(m["name"], m["topic"], m["status"]) for m in inbox] == [("Chi", "partner", "new")]
    assert c.get("/api/v1/admin/stats", headers=admin).json()["new_messages"] == 1
    mid = inbox[0]["id"]
    assert c.patch(f"/api/v1/admin/messages/{mid}", json={"status": "done"}, headers=admin).status_code == 200
    assert c.get("/api/v1/admin/messages?status=new", headers=admin).json() == []
    assert c.delete(f"/api/v1/admin/messages/{mid}", headers=admin).status_code == 200
    assert c.get("/api/v1/admin/messages", headers=admin).json() == []
    assert c.delete(f"/api/v1/admin/messages/{mid}", headers=admin).status_code == 404


def test_contact_form_rejects_bad_input_drops_bots_and_slows_floods(tmp_path):
    c, store = make(tmp_path)
    assert c.post("/api/v1/contact", json={**MESSAGE, "email": "khong-phai-email"}).status_code == 422
    assert c.post("/api/v1/contact", json={**MESSAGE, "message": "ngắn"}).status_code == 422
    assert c.post("/api/v1/contact", json={**MESSAGE, "website": "http://spam"}).json() == {"ok": True}
    assert store.messages() == []  # the honeypot was filled: nothing stored
    for _ in range(4):
        assert c.post("/api/v1/contact", json=MESSAGE).status_code == 200
    assert c.post("/api/v1/contact", json=MESSAGE).status_code == 429


def test_deleting_the_account_deletes_its_messages_and_usage(tmp_path):
    c, store = make(tmp_path)
    headers, user = signup(c)
    assert c.post("/api/v1/contact", json=MESSAGE, headers=headers).status_code == 200
    assert c.post("/api/v1/plans/preview", json=trip_payload(), headers=headers).status_code == 200
    assert store.messages()[0]["user_id"] == user["id"] and store.usage_today(user["id"]) == {"plan": 1}
    assert c.post("/api/v1/me/delete", json={"password": PASSWORD}, headers=headers).status_code == 200
    assert store.messages() == [] and store.usage_today(user["id"]) == {}


def test_password_reset_links_use_the_public_address(tmp_path):
    c, _ = make(tmp_path, travelmate_public_url="https://travelmate.example.vn")
    admin, _ = signup(c, "admin@example.com", "Quản trị")
    _, member = signup(c, "lan@example.com", "Lan")
    link = c.post(f"/api/v1/admin/users/{member['id']}/reset-link", headers=admin).json()["link"]
    assert link.startswith("https://travelmate.example.vn/?view=forgot&reset=")
