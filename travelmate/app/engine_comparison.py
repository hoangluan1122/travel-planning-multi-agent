"""Compare the ADK and MAF engines on the same inputs.

A PlannerInput case runs through PlannerSpecialist and a RecommendationRequest case
through RecommendationSpecialist, `runs` times per engine, so both engines face the same
submit gate and validation. The report records only agent, outcome, error type and
latency: no prompts, drafts or model text.
"""

import statistics
import time
from dataclasses import asdict, dataclass

from .models import Context


@dataclass
class EngineRun:
    engine: str
    agent: str
    case: str
    run: int
    outcome: str  # accepted | rejected | timeout | error
    error_type: str | None
    duration_ms: int


def build_agent(engine, model_factory, data):
    from .adk_adapter import AdkPlanner
    from .maf_adapter import MafPlanner
    from .models import PlannerInput
    from .specialists.planner import PlannerSpecialist
    from .specialists.recommendation import RecommendationRequest, RecommendationSpecialist

    if isinstance(data, PlannerInput):
        return PlannerSpecialist(model_factory, MafPlanner if engine == "maf" else AdkPlanner)
    if isinstance(data, RecommendationRequest):
        return RecommendationSpecialist(model_factory, engine=engine)
    raise TypeError(f"Unsupported comparison case: {type(data).__name__}")


async def run_once(engine, model_factory, case_name, data, run, timeout):
    from .agents import AgentError

    agent = build_agent(engine, model_factory, data)
    started = time.monotonic()
    outcome, error_type = "accepted", None
    try:
        await agent.run(data, Context(), timeout=timeout)
    except AgentError as exc:
        outcome, error_type = "rejected", type(exc).__name__
    except TimeoutError:
        outcome, error_type = "timeout", "TimeoutError"
    except Exception as exc:  # provider/network failures count against the engine run
        outcome, error_type = "error", type(exc).__name__
    duration = int((time.monotonic() - started) * 1000)
    return EngineRun(engine, agent.name, case_name, run, outcome, error_type, duration)


def summarize(results, key=lambda r: r.engine):
    summary = {}
    for group in sorted({key(r) for r in results}):
        rows = [r for r in results if key(r) == group]
        accepted = [r for r in rows if r.outcome == "accepted"]
        durations = [r.duration_ms for r in rows]
        errors = {}
        for r in rows:
            if r.error_type:
                errors[r.error_type] = errors.get(r.error_type, 0) + 1
        summary[group] = {
            "runs": len(rows),
            "accepted": len(accepted),
            "accept_rate": round(len(accepted) / len(rows), 3) if rows else 0.0,
            "median_ms": int(statistics.median(durations)) if durations else 0,
            "max_ms": max(durations) if durations else 0,
            "errors": errors,
        }
    return summary


async def compare(cases, engines, runs=3, timeout=90):
    """cases: {name: PlannerInput | RecommendationRequest}; engines: {"adk"|"maf": model_factory}.

    Runs are sequential and alternate engines, so they do not compete for one rate limit
    and drift in provider latency hits both alike.
    """
    results = []
    for case_name, data in cases.items():
        for run in range(1, runs + 1):
            for engine, factory in engines.items():
                results.append(await run_once(engine, factory, case_name, data, run, timeout))
    return {
        "summary": summarize(results),
        "by_case": summarize(results, key=lambda r: f"{r.case} · {r.engine}"),
        "runs": [asdict(r) for r in results],
    }


def markdown(report, model):
    def table(title, rows):
        out = [
            f"| {title} | Lượt chạy | Được chấp nhận | Tỷ lệ | Trung vị (ms) | Lâu nhất (ms) | Lỗi |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, s in rows.items():
            errors = ", ".join(f"{k}×{v}" for k, v in s["errors"].items()) or "—"
            out.append(
                f"| {name} | {s['runs']} | {s['accepted']} | {s['accept_rate']:.0%} | "
                f"{s['median_ms']} | {s['max_ms']} | {errors} |"
            )
        return out

    lines = [f"# So sánh engine: ADK vs MAF (model `{model}`)", "", "## Tổng", ""]
    lines += table("Engine", report["summary"])
    if "by_case" in report:
        lines += ["", "## Theo đầu vào", ""] + table("Đầu vào · engine", report["by_case"])
    lines += ["", "Chỉ ghi kết quả, loại lỗi và thời gian; không lưu prompt, bản nháp hay văn bản của model."]
    return "\n".join(lines) + "\n"
