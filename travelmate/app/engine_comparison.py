"""Compare the ADK and MAF engines on the same planner inputs.

Each engine plans every case `runs` times through PlannerSpecialist, so both face the
same submit gate and validation. The report records only outcome, error type and
latency: no prompts, drafts or model text.
"""

import statistics
import time
from dataclasses import asdict, dataclass

from .models import Context


@dataclass
class EngineRun:
    engine: str
    case: str
    run: int
    outcome: str  # accepted | rejected | timeout | error
    error_type: str | None
    duration_ms: int


async def run_once(engine, planner_cls, model_factory, case_name, data, run, timeout):
    from .agents import AgentError
    from .specialists.planner import PlannerSpecialist

    started = time.monotonic()
    outcome, error_type = "accepted", None
    try:
        await PlannerSpecialist(model_factory, planner_cls).run(data, Context(), timeout=timeout)
    except AgentError as exc:
        outcome, error_type = "rejected", type(exc).__name__
    except TimeoutError:
        outcome, error_type = "timeout", "TimeoutError"
    except Exception as exc:  # provider/network failures count against the engine run
        outcome, error_type = "error", type(exc).__name__
    return EngineRun(engine, case_name, run, outcome, error_type, int((time.monotonic() - started) * 1000))


def summarize(results):
    summary = {}
    for engine in sorted({r.engine for r in results}):
        rows = [r for r in results if r.engine == engine]
        accepted = [r for r in rows if r.outcome == "accepted"]
        durations = [r.duration_ms for r in rows]
        errors = {}
        for r in rows:
            if r.error_type:
                errors[r.error_type] = errors.get(r.error_type, 0) + 1
        summary[engine] = {
            "runs": len(rows),
            "accepted": len(accepted),
            "accept_rate": round(len(accepted) / len(rows), 3) if rows else 0.0,
            "median_ms": int(statistics.median(durations)) if durations else 0,
            "max_ms": max(durations) if durations else 0,
            "errors": errors,
        }
    return summary


async def compare(cases, engines, runs=3, timeout=90):
    """cases: {name: PlannerInput}; engines: {name: (planner_cls, model_factory)}.

    Runs are sequential so engines do not compete for the same rate limit.
    """
    results = []
    for case_name, data in cases.items():
        for run in range(1, runs + 1):
            for engine, (planner_cls, factory) in engines.items():
                results.append(await run_once(engine, planner_cls, factory, case_name, data, run, timeout))
    return {"summary": summarize(results), "runs": [asdict(r) for r in results]}


def markdown(report, model):
    lines = [
        f"# So sánh engine planner: ADK vs MAF (model `{model}`)",
        "",
        "| Engine | Lượt chạy | Được chấp nhận | Tỷ lệ | Trung vị (ms) | Lâu nhất (ms) | Lỗi |",
        "|---|---|---|---|---|---|---|",
    ]
    for engine, s in report["summary"].items():
        errors = ", ".join(f"{k}×{v}" for k, v in s["errors"].items()) or "—"
        lines.append(
            f"| {engine} | {s['runs']} | {s['accepted']} | {s['accept_rate']:.0%} | "
            f"{s['median_ms']} | {s['max_ms']} | {errors} |"
        )
    lines += ["", "Chỉ ghi kết quả, loại lỗi và thời gian; không lưu prompt, bản nháp hay văn bản của model."]
    return "\n".join(lines) + "\n"
