"""scripts/check_live_site.py against a real server (demo mode), so the live check cannot rot.

The external sources (Open-Meteo, Photon, Wikipedia) are not called here; only the site checks.
"""

import importlib.util
import socket
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_live_site.py"
TOKEN = "live-check-operator-token"


def load():
    spec = importlib.util.spec_from_file_location("check_live_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    from app.main import Settings, create_app
    from app.memory.store import Store

    store = Store(tmp_path_factory.mktemp("live") / "live.sqlite3")
    app = create_app(Settings(_env_file=None, travelmate_api_token=TOKEN), store=store)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    for _ in range(100):
        if instance.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


def test_site_checks_pass_on_a_running_server(server):
    checker = live.Checker(server, token=TOKEN, wake_s=20)
    for fn in (checker.wake, checker.home, checker.pages, checker.guard, checker.plan):
        status, detail = fn()
        assert status in {live.OK, live.WARN}, (fn.__name__, detail)
    assert "tệp giao diện" in checker.home()[1]


def test_demo_mode_or_no_token_is_a_failed_configuration(server):
    checker = live.Checker(server, wake_s=20)
    checker.wake()
    status, detail = checker.configuration()
    assert status == live.FAIL and "mode=demo" in detail
    checker.health = {"mode": "live", "token_required": True, "database": "sqlite"}
    assert checker.configuration()[0] == live.WARN  # data would be lost on each deploy


def test_a_plan_without_a_token_is_refused(server):
    status, detail = live.Checker(server, wake_s=20).plan()
    assert status == live.FAIL and "401" in detail


def test_a_dead_site_fails_and_sets_the_exit_code(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens here once the socket closes
    monkeypatch.setattr(live.time, "sleep", lambda s: None)
    assert live.main([f"http://127.0.0.1:{port}", "--wake-seconds", "1"]) == 1
    assert "✗" in summary.read_text(encoding="utf-8")


def test_missing_place_sources_warn_only_when_wikipedia_is_left(monkeypatch):
    checker = live.Checker("https://example.test")

    def fake(answers):
        def request(url, data=None, token=None, timeout=30):
            for host, status in answers.items():
                if host in url:
                    if status is None:
                        raise TimeoutError("hung")
                    return live.Response(status, {}, "{}")
            raise AssertionError(url)
        return request

    monkeypatch.setattr(live, "request", fake({"photon": None, "wikipedia": 200}))
    assert checker.place_sources()[0] == live.WARN
    monkeypatch.setattr(live, "request", fake({"photon": 502, "wikipedia": None}))
    assert checker.place_sources()[0] == live.FAIL
