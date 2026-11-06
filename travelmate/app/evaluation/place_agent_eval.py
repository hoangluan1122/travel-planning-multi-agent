"""Repeatable evaluation of the LLM Place Agent on fixed cases, per engine.

Each case runs through LivePlaceAgent (the same path as LIVE_PLACE_MODE=adk_llm/maf_llm).
Ambiguous destinations use the top location option, as a user click would, and the
choice is recorded. Metrics come only from the report: status, number of places,
searches and details used, keywords the LLM chose (from the trace), whether the last
search was widened, whether every place is backed by a source, and latency.
"""

import statistics
import time

from app.core.models import Context
from app.place_agent.live import LivePlaceAgent, LivePlaceRequest
from app.tools.places.place_media import plain

GOOD = {"success", "partial"}


def keywords_from_trace(report):
    words = []
    for event in report.trace:
        if event.step != "search":
            continue
        if event.message.startswith("Từ khoá “"):
            words.append(event.message.split("“", 1)[1].split("”", 1)[0])
        elif event.message.startswith("Tìm rộng"):
            words.append("")
    return words


async def run_case(case, engine, model_factory, geo):
    request = LivePlaceRequest(
        destination=case["destination"], category=case["category"], needs=case.get("needs", ""),
        limit=case.get("limit", 5),
    )
    row = {"case": case["id"], "engine": engine}
    started = time.monotonic()
    try:
        resolved = await LivePlaceAgent(geo_service=geo).run(request, Context(), 60)
        if resolved.status == "needs_location" and resolved.location_options:
            choice = resolved.location_options[0]
            row["chosen_location"] = f"{choice.name}, {choice.admin1}".strip(", ")
            request = request.model_copy(update={"location_id": choice.id})
        report = await LivePlaceAgent(model_factory=model_factory, geo_service=geo, engine=engine).run(
            request, Context(), 140
        )
        sources = {s.url for s in report.sources}
        row |= {
            "status": report.status,
            "places": len(report.places),
            "grounded": all(p.source_url in sources for p in report.places),
            "search_calls": report.search_calls,
            "detail_calls": report.detail_calls,
            "keywords": keywords_from_trace(report),
            "place_names": [p.name for p in report.places],
        }
        expected = [plain(t) for t in case.get("expect_any", [])]
        if expected:
            hits = sum(1 for p in report.places if any(t in plain(p.name) for t in expected))
            row["needs_hits"] = hits
    except Exception as exc:  # keep evaluating the other cases
        row |= {"status": "exception", "error_type": type(exc).__name__, "places": 0, "grounded": True}
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    return row


def summarize(rows):
    out = {}
    for engine in sorted({r["engine"] for r in rows}):
        mine = [r for r in rows if r["engine"] == engine]
        good = [r for r in mine if r["status"] in GOOD]
        out[engine] = {
            "runs": len(mine),
            "success": len(good),
            "success_rate": round(len(good) / len(mine), 3) if mine else 0.0,
            "avg_places": round(sum(r["places"] for r in mine) / len(mine), 2) if mine else 0.0,
            "all_grounded": all(r.get("grounded", True) for r in mine),
            "broad_first_rate": round(
                sum(1 for r in mine if r.get("keywords") and r["keywords"][0] == "") / len(mine), 3
            ) if mine else 0.0,
            "needs_match_rate": round(
                sum(1 for r in judged if r["needs_hits"] > 0) / len(judged), 3
            ) if (judged := [r for r in mine if "needs_hits" in r]) else None,
            "needs_hit_share": round(
                sum(r["needs_hits"] for r in judged) / max(1, sum(r["places"] for r in judged)), 3
            ) if judged else None,
            "median_ms": int(statistics.median(r["duration_ms"] for r in mine)) if mine else 0,
            "statuses": {s: sum(1 for r in mine if r["status"] == s) for s in sorted({r["status"] for r in mine})},
        }
    return out


async def evaluate(cases, engines, geo, runs=1, pause_s=0.0):
    """engines: {"adk"|"maf": model_factory}. Sequential, alternating engines per case.

    pause_s spaces runs out so the public place source does not throttle the evaluation;
    a throttled source shows up as source_error, which would otherwise skew the numbers.
    """
    import asyncio

    rows = []
    for case in cases:
        for _ in range(runs):
            for engine, factory in engines.items():
                if rows and pause_s:
                    await asyncio.sleep(pause_s)
                rows.append(await run_case(case, engine, factory, geo))
    return {"summary": summarize(rows), "runs": rows}


def pct(value):
    return "—" if value is None else f"{value:.0%}"


def markdown(report, model):
    lines = [
        f"# Đánh giá Place Agent — ADK vs MAF (model `{model}`)", "",
        "| Engine | Lượt | Thành công | Tỷ lệ | TB số địa điểm | Mọi địa điểm có nguồn | Ca đúng nhu cầu | Địa điểm đúng nhu cầu | Tìm rộng trước | Trung vị (ms) | Trạng thái |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for engine, s in report["summary"].items():
        statuses = ", ".join(f"{k}×{v}" for k, v in s["statuses"].items())
        lines.append(
            f"| {engine} | {s['runs']} | {s['success']} | {s['success_rate']:.0%} | {s['avg_places']} | "
            f"{'✅' if s['all_grounded'] else '❌'} | {pct(s['needs_match_rate'])} | {pct(s['needs_hit_share'])} | "
            f"{s['broad_first_rate']:.0%} | {s['median_ms']} | {statuses} |"
        )
    lines += ["", "## Từng ca", "",
              "| Ca | Engine | Trạng thái | Số địa điểm | Đúng nhu cầu | Lượt tìm | Từ khoá LLM chọn | ms |",
              "|---|---|---|---|---|---|---|---|"]
    for r in report["runs"]:
        words = ", ".join(f"“{w}”" if w else "(rộng)" for w in r.get("keywords", [])) or "—"
        lines.append(
            f"| {r['case']} | {r['engine']} | {r['status']} | {r['places']} | {r.get('needs_hits', '—')} | "
            f"{r.get('search_calls', '—')} | "
            f"{words} | {r['duration_ms']} |"
        )
    return "\n".join(lines) + "\n"
