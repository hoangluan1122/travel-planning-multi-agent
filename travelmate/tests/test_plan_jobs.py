"""Plans as background jobs: start at once, poll the real stage, saved for a signed-in user."""

import asyncio
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient
from test_accounts import Provider, signup, trip_payload

from app.agents.plan_jobs import PlanJobs, report
from app.core.base import AgentError
from app.main import Settings, build_services, create_app
from app.memory.store import Store

OPERATOR = {"Authorization": "Bearer operator-token"}


@contextmanager
def app_client(tmp_path, orchestrator=None, **overrides):
    store = Store(tmp_path / "jobs.sqlite3", admin_email="admin@example.com")
    settings = Settings(_env_file=None, travelmate_api_token="operator-token", **overrides)
    # As a context manager the client keeps one event loop, so background jobs keep running.
    with TestClient(create_app(settings, orchestrator=orchestrator, provider=Provider(), store=store)) as client:
        yield client, store


def wait(client, job_id, headers, until=("done", "failed")):
    for _ in range(200):
        view = client.get(f"/api/v1/plans/jobs/{job_id}", headers=headers).json()
        if view["status"] in until:
            return view
        time.sleep(0.02)
    raise AssertionError(f"job still {view}")


class Gated:
    """An orchestrator that reports a stage, then waits until the test lets it finish."""

    def __init__(self, error=None):
        self.release, self.error, self.inner = None, error, None

    async def plan(self, trip):
        self.release = self.release or asyncio.Event()
        report("scheduling", round=2)
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return await self.inner.plan(trip)


def test_a_signed_in_plan_runs_in_the_background_and_is_saved_to_the_trips(tmp_path):
    with app_client(tmp_path, travelmate_daily_plans=3) as (c, _):
        headers, _ = signup(c)
        started = c.post("/api/v1/plans/jobs", json=trip_payload(), headers=headers)
        assert started.status_code == 202 and started.json()["status"] == "running"
        view = wait(c, started.json()["job_id"], headers)
        assert view["status"] == "done" and view["result"]["draft"]["days"]
        assert view["stage"] in {"budget", "saving"} and view["error"] is None
        trips = c.get("/api/v1/me/trips", headers=headers).json()
        assert [t["id"] for t in trips] == [view["trip_id"]]
        assert trips[0]["title"].startswith("Huế · ")
        assert c.get("/api/v1/me/usage", headers=headers).json()["plan"]["used"] == 1


def test_the_page_sees_the_real_stage_and_one_plan_runs_at_a_time(tmp_path):
    gated = Gated()
    gated.inner = build_services(Settings(_env_file=None), provider=Provider()).orchestrator
    with app_client(tmp_path, orchestrator=gated) as (c, _):
        job_id = c.post("/api/v1/plans/jobs", json=trip_payload(), headers=OPERATOR).json()["job_id"]
        view = wait(c, job_id, OPERATOR, until=("running",))
        for _ in range(100):
            if view["stage"] == "scheduling":
                break
            time.sleep(0.02)
            view = c.get(f"/api/v1/plans/jobs/{job_id}", headers=OPERATOR).json()
        assert view["stage"] == "scheduling" and "(lần 2)" in view["stage_label"]
        second = c.post("/api/v1/plans/jobs", json=trip_payload(), headers=OPERATOR)
        assert second.status_code == 409 and second.json()["detail"]["job_id"] == job_id
        c.portal.call(gated.release.set)
        assert wait(c, job_id, OPERATOR)["status"] == "done"


def test_someone_else_cannot_read_a_job(tmp_path):
    with app_client(tmp_path) as (c, _):
        headers, _ = signup(c)
        job_id = c.post("/api/v1/plans/jobs", json=trip_payload(), headers=headers).json()["job_id"]
        other, _ = signup(c, "binh@example.com", "Bình")
        assert c.get(f"/api/v1/plans/jobs/{job_id}", headers=other).status_code == 404
        assert c.get(f"/api/v1/plans/jobs/{job_id}", headers=OPERATOR).status_code == 404
        c.cookies.clear()  # the client kept the last sign-in's cookie
        assert c.get(f"/api/v1/plans/jobs/{job_id}").status_code == 401


def test_failures_become_a_message_and_are_not_counted(tmp_path):
    for error, status, text in [(AgentError("Nguồn địa điểm không phản hồi"), 502, "không phản hồi"),
                                (TimeoutError(), 504, "Quá thời gian"), (RuntimeError("boom"), 502, "Chưa tạo được")]:
        class Failing:
            async def plan(self, trip, error=error):
                raise error

        with app_client(tmp_path, orchestrator=Failing(), travelmate_daily_plans=1) as (c, store):
            headers, _ = signup(c, f"u{status}{len(text)}@example.com", "An")
            job_id = c.post("/api/v1/plans/jobs", json=trip_payload(), headers=headers).json()["job_id"]
            view = wait(c, job_id, headers)
            assert view["status"] == "failed" and view["error_status"] == status and text in view["error"]
            assert "boom" not in view["error"]  # internal errors are not shown
            assert c.get("/api/v1/me/usage", headers=headers).json()["plan"]["used"] == 0


def test_the_daily_limit_is_checked_before_a_job_starts(tmp_path):
    with app_client(tmp_path, travelmate_daily_plans=1) as (c, _):
        headers, _ = signup(c)
        wait(c, c.post("/api/v1/plans/jobs", json=trip_payload(), headers=headers).json()["job_id"], headers)
        assert c.post("/api/v1/plans/jobs", json=trip_payload(), headers=headers).status_code == 429


def test_report_outside_a_job_does_nothing_and_old_jobs_are_pruned():
    report("places")  # no job: no error

    async def scenario():
        jobs = PlanJobs(keep_s=0)

        async def work(job):
            job.result = {"ok": True}

        job = jobs.start("user:1", work)
        await asyncio.sleep(0.01)
        assert jobs.get(job.id, "user:1").status == "done" and jobs.get(job.id, "user:2") is None
        time.sleep(0.01)
        jobs.prune()
        assert jobs.get(job.id, "user:1") is None

    asyncio.run(scenario())
