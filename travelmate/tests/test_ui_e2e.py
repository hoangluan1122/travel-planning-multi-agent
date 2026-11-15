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
    yield f"http://127.0.0.1:{port}/"
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
    page.wait_for_function("document.querySelector('#tm-fav')?.getAttribute('aria-pressed') === 'true'")
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


def test_guest_is_led_to_sign_in_and_keeps_the_trip(server, browser):
    """A visitor starts from the home page, is asked to sign in only when planning, and loses nothing."""
    errors = []
    context = browser.new_context()
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    # Home: the quick form carries the destination into the trip form.
    page.goto(server)
    assert page.locator("footer.tm-footer").count() == 1
    page.fill(".tm-quick input[name=destination]", "Huế")
    page.click(".tm-quick button")
    page.wait_for_url("**view=create**")
    assert page.input_value("[data-form=create] [name=destination]") == "Huế"
    page.wait_for_selector("[data-form=create] .tm-note")  # this server needs an account

    # Planning as a guest goes to sign-in; signing up continues straight to the plan.
    page.locator("[data-form=create]").evaluate("f => f.requestSubmit()")
    page.wait_for_url("**view=login**")
    page.click(".tm-auth-switch a[href*='view=signup']")
    page.wait_for_selector("#tm-auth input[name=name]")
    page.fill("#tm-auth input[name=name]", "Khách UI")
    page.fill("#tm-auth input[name=email]", "guest@travelmate.test")
    page.fill("#tm-auth input[name=password]", "test-guest-pass-1")
    page.click("#tm-auth button")
    page.wait_for_url("**view=plan**")
    page.wait_for_selector("#tm-plan-account .tm-badge")
    assert "Huế" in page.inner_text(".tm-plan-hero")

    # The plan link works in a new tab too (plans are kept per tab): it is found among the saved trips.
    assert "id=" in page.url
    other = context.new_page()
    other.on("pageerror", lambda exc: errors.append(str(exc)))
    other.goto(page.url.replace("view=plan", "view=day") + "&day=1")
    other.wait_for_selector(".tm-day-head")
    assert "Ngày 2" in other.inner_text(".tm-day-head")
    other.close()

    # Rename and delete use in-page dialogs.
    page.goto(f"{server}?view=saved")
    page.click("[data-rename]")
    page.fill(".tm-dialog input", "Huế cuối tuần")
    page.click(".tm-dialog button[value=ok]")
    page.wait_for_selector(".tm-trip-card h3:has-text('Huế cuối tuần')")
    page.click("[data-delete]")
    page.click(".tm-dialog button[value=ok]")
    page.wait_for_selector("text=Chưa có chuyến đi nào.")

    # An unknown address gets a not-found page, not a blank one.
    page.goto(f"{server}?view=khong-co")
    assert "Không tìm thấy trang" in page.inner_text("main.visible")

    assert not errors, errors
    context.close()


def test_company_pages_and_contact_inbox(server, browser):
    """A visitor reads the pricing and privacy pages and writes in; an admin finds the message."""
    errors = []
    context = browser.new_context()
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto(f"{server}?view=pricing")
    assert "Lập lịch trình bằng AI: 10 mỗi ngày" in page.inner_text(".tm-plan-card.featured")
    page.click(".tm-footer a[href='?view=privacy']")
    page.wait_for_selector("text=Bên thứ ba xử lý dữ liệu")
    assert page.title() == "Chính sách bảo mật — TravelMate"

    page.goto(f"{server}?view=contact&topic=partner")
    assert page.input_value("#tm-contact [name=topic]") == "partner"
    page.fill("#tm-contact [name=name]", "Khách hợp tác")
    page.fill("#tm-contact [name=email]", "doitac@travelmate.test")
    page.fill("#tm-contact [name=message]", "Công ty chúng tôi muốn dùng TravelMate cho khách.")
    page.click("#tm-contact button")
    page.wait_for_selector(".tm-sent")

    # The admin (signed up in another test, or now) sees it under Quản trị → Liên hệ.
    page.goto(f"{server}?view=login")
    page.fill("#tm-auth input[name=email]", ADMIN[0])
    page.fill("#tm-auth input[name=password]", ADMIN[1])
    page.click("#tm-auth button")
    page.wait_for_timeout(1500)
    if "view=login" in page.url:
        sign_up(page, server, ADMIN[0], ADMIN[1], "Quản trị")
    page.goto(f"{server}?view=admin-messages")
    page.wait_for_selector(".tm-message:has-text('Khách hợp tác')")
    page.click(".tm-message button[data-status=done]")
    page.wait_for_selector("text=Không có tin nhắn nào.")

    assert not errors, errors
    context.close()
