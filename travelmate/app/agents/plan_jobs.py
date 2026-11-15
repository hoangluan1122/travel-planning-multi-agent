"""Plans as background jobs, with the stage the pipeline is really at.

A plan takes from about 30 seconds to a few minutes (map lookups, then Gemini, with retries
when the free quota pushes back). Holding one HTTP request open that long breaks on slow
networks and proxies, and the page could only guess what was happening. Instead the page
starts a job, gets its id at once and asks for its state every couple of seconds; the job
keeps running (and, for a signed-in user, saves the trip) even if the tab is closed.

Stages come from the orchestrators through report(), which reads a context variable set
for the job's task, so agents need no extra parameter and calls outside a job do nothing.
Jobs live in this process's memory: one web process (Render free) is the deployment target.
"""

import asyncio
import contextvars
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

_PROGRESS = contextvars.ContextVar("plan_progress", default=None)

# What the page shows for each stage, in pipeline order.
STAGES = {
    "queued": "Đang bắt đầu…",
    "places": "Đang tìm địa danh, quán ăn, nơi ở và dự báo thời tiết…",
    "searching": "Đang tìm thêm các địa điểm bạn yêu cầu…",
    "ranking": "Đang chọn và xếp hạng địa điểm…",
    "scheduling": "Gemini đang xếp lịch từng ngày…",
    "revising": "Đang sửa lịch theo kết quả tự kiểm tra…",
    "budget": "Đang tính chi phí…",
    "saving": "Đang lưu vào Chuyến đi của tôi…",
}


def report(stage, **info):
    """Tell the job running this plan (if any) which stage it reached."""
    callback = _PROGRESS.get()
    if callback is not None:
        callback(stage, info)


@dataclass
class PlanJob:
    id: str
    owner: str
    status: str = "running"  # running | done | failed
    stage: str = "queued"
    round: int | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    result: dict | None = None
    error: str | None = None
    error_status: int | None = None
    trip_id: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    def update(self, stage, info):
        if stage in STAGES and self.status == "running":
            self.stage, self.round = stage, info.get("round")

    def fail(self, status, message):
        self.status, self.error_status, self.error, self.finished = "failed", status, message, time.time()

    def view(self):
        label = STAGES[self.stage]
        if self.stage in {"scheduling", "revising"} and self.round and self.round > 1:
            label = label.rstrip("…") + f" (lần {self.round})…"
        return {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "stage_label": label,
            "elapsed_s": round((self.finished or time.time()) - self.started, 1),
            "result": self.result,
            "trip_id": self.trip_id,
            "error": self.error,
            "error_status": self.error_status,
        }


class PlanJobs:
    """At most one running job per owner; finished jobs are kept for keep_s, at most max_jobs."""

    def __init__(self, keep_s=3600, max_jobs=500):
        self.keep_s, self.max_jobs = keep_s, max_jobs
        self.jobs = OrderedDict()

    def prune(self):
        now = time.time()
        for job_id, job in list(self.jobs.items()):
            if job.finished and now - job.finished > self.keep_s:
                del self.jobs[job_id]
        while len(self.jobs) > self.max_jobs:
            oldest = next((j for j in self.jobs.values() if j.status != "running"), None)
            if oldest is None:
                break
            del self.jobs[oldest.id]

    def running_for(self, owner):
        return next((j for j in self.jobs.values() if j.owner == owner and j.status == "running"), None)

    def get(self, job_id, owner):
        job = self.jobs.get(job_id)
        return job if job is not None and job.owner == owner else None

    def start(self, owner, work):
        """Run work(job) in the background; work sets job.result (and job.trip_id) or raises.

        work must turn expected failures into job.fail(status, message); anything it lets
        escape becomes a generic failure here.
        """
        self.prune()
        job = PlanJob(id=uuid.uuid4().hex, owner=owner)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, work))
        return job

    async def _run(self, job, work):
        _PROGRESS.set(job.update)  # this task's own context: inner tasks inherit it
        try:
            await work(job)
            if job.status == "running":
                job.status, job.finished = "done", time.time()
        except asyncio.CancelledError:
            job.fail(503, "Máy chủ đã dừng khi đang tạo lịch trình. Vui lòng thử lại.")
            raise
        except Exception:
            job.fail(502, "Chưa tạo được lịch trình. Vui lòng thử lại.")
        finally:
            job.task = None
