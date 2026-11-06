"""End-to-end UI test in a real browser (Playwright): the product flows a user and an admin take.

Runs the API in demo mode on a free local port with a temporary SQLite database. Uses an
installed Chromium-family browser (Edge, Chrome, or Playwright's own Chromium); skipped when
none is available. Test accounts below exist only in that temporary database.
"""

import socket
import threading
import time
from datetime import date, timedelta

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ADMIN = ("admin@travelmate.test", "test-admin-pass-1")
MEMBER = ("member@travelmate.test", "test-member-pass-1")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    from app.main import Settings, create_app
    from app.memory.store import Store

    store = Store(tmp_path_factory.mktemp("ui") / "ui.sqlite3", admin_email=ADMIN[0])
    app = create_app(Settings(_env_file=None, travelmate_api_token="ui-operator-token"), store=store)
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    for _ in range(100):
        if instance.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/ui/travelmate-v2/index.html"
    instance.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        for options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                instance = p.chromium.launch(**options)
                break
            except Exception:
                continue
        else:
            pytest.skip("No Chromium-family browser available")
        yield instance
        instance.close()


def sign_up(page, base, email, password, name):
    page.goto(f"{base}?view=signup")
    page.fill("#tm-auth input[name=name]", name)
    page.fill("#tm-auth input[name=email]", email)
    page.fill("#tm-auth input[name=password]", password)
    page.click("#tm-auth button")
    page.wait_for_url("**view=saved**")


def test_member_and_admin_flows(server, browser):
    errors = []
    context = browser.new_context()
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    # Admin signs up first (TRAVELMATE_ADMIN_EMAIL), then a member.
    sign_up(page, server, *ADMIN, "Quản trị UI")
    assert page.locator("header nav a[href='?view=admin']").count() == 1
    assert page.evaluate("localStorage.getItem('tm-session')").find("token") == -1  # token only in the cookie
    page.goto(f"{server}?view=profile")
    page.click("#tm-logout")
    page.wait_for_url("**view=home**")
    sign_up(page, server, *MEMBER, "Thành viên UI")

    # Create a trip: saved to the account automatically.
    page.goto(f"{server}?view=create")
    start = date.today() + timedelta(days=3)
    page.fill("[data-form=create] [name=destination]", "Huế")
    page.fill("[data-form=create] [name=start]", start.isoformat())
    page.fill("[data-form=create] [name=end]", (start + timedelta(1)).isoformat())
    page.fill("[data-form=create] [name=people]", "2")
    page.fill("[data-form=create] [name=budget]", "5000000")
    page.locator("[data-form=create]").evaluate("f => f.requestSubmit()")
    page.wait_for_url("**view=plan**")
    page.wait_for_selector("#tm-plan-account .tm-badge")
    assert "Đã lưu vào tài khoản" in page.inner_text("#tm-plan-account")

    # Place page from the day view: favourite and review.
    request_id = page.evaluate("JSON.parse(sessionStorage.getItem('tm-plans'))[0].result.request_id")
    page.goto(f"{server}?view=day&id={request_id}&day=0")
    page.click("#connected-view h3 a")
    page.wait_for_selector("#tm-fav")
    page.click("#tm-fav")
    page.wait_for_function("document.querySelector('#tm-fav')?.textContent === '♥'")
    place_id = page.evaluate("new URLSearchParams(location.search).get('id')")
    page.goto(f"{server}?view=review&id={place_id}")
    page.wait_for_selector("#tm-review")
    page.check("#tm-review input[value='5']")
    page.fill("#tm-review textarea", "Rất đẹp và yên tĩnh, nên đi sớm.")
    page.click("#tm-review button.dark")
    page.wait_for_url(f"**view=place&id={place_id}**")
    page.wait_for_selector("text=Chờ duyệt")

    # Edit the trip: add a cost, auto-arrange via the API flow in the editor.
    trip_id = page.evaluate("JSON.parse(sessionStorage.getItem('tm-plans'))[0].trip_id")
    page.goto(f"{server}?view=edit&id={trip_id}")
    page.wait_for_selector("#tm-save-edit")
    page.click("#tm-cost-add")
    page.fill("[data-cost='0'][data-ck='label']", "Khách sạn 1 đêm")
    page.fill("[data-cost='0'][data-ck='amount_vnd']", "700000")
    page.click("#tm-save-edit")
    page.wait_for_url("**view=plan**")
    page.wait_for_selector("#tm-plan-account")
    assert "chỉnh sửa" in page.inner_text("#tm-plan-account")
    assert "do bạn nhập" in page.inner_text("#connected-view")

    # Chat: a compound question gets two specialists; the conversation is saved.
    page.goto(f"{server}?view=chat")
    page.fill("#tm-chat-form input", "tìm quán ăn ở Huế và thời tiết thế nào")
    page.locator("#tm-chat-form").evaluate("f => f.requestSubmit()")
    page.wait_for_function("document.querySelectorAll('#tm-chat-log .chat-msg.bot').length >= 2")
    badges = page.locator("#tm-chat-log .chat-agent").all_inner_texts()
    assert any("ĐỊA ĐIỂM" in b.upper() for b in badges) and any("THỜI TIẾT" in b.upper() for b in badges)
    page.wait_for_selector("[data-open-chat]")

    # Admin approves the review; the member then sees it published.
    page.goto(f"{server}?view=profile")
    page.click("#tm-logout")
    page.wait_for_url("**view=home**")
    page.goto(f"{server}?view=login")
    page.fill("#tm-auth input[name=email]", ADMIN[0])
    page.fill("#tm-auth input[name=password]", ADMIN[1])
    page.click("#tm-auth button")
    page.wait_for_url("**view=saved**")
    page.goto(f"{server}?view=moderation")
    page.wait_for_selector("[data-action=approve]")
    page.click("[data-action=approve]")
    page.wait_for_selector("text=Không có đánh giá chờ duyệt.")
    page.goto(f"{server}?view=admin")
    page.wait_for_selector(".tm-stats")
    assert "Người dùng" in page.inner_text(".tm-stats")
    page.goto(f"{server}?view=place&id={place_id}")
    page.wait_for_selector("text=5/5 từ 1 đánh giá TravelMate")

    assert not errors, errors
    context.close()
