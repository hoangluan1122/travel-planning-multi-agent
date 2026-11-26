"""Graded conversations for the AI assistant: run fixed cases, check each answer, score them.

A case (assistant_cases.json) is one chat session: a list of user messages and what the last
answer must satisfy, such as which specialists answered, how many places came back, whether
sources were cited, whether the plan says it is over budget, and text that must or must not
appear. grade() checks one answer and returns the failed checks; nothing in it calls a model,
so tests can grade made-up answers. run_case() and evaluate() drive a real ChatService.

Every answer is also checked for leaks: the API key and the agents' own instructions or tool
names must never reach the user.
"""

# Bộ đánh giá Trợ lý AI: chạy các hội thoại mẫu, chấm từng câu trả lời theo tiêu chí ghi sẵn, rồi tính
# điểm theo nhóm. grade() chỉ chấm, không gọi model, nên test chấm được câu trả lời giả.

import asyncio
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

CASES = Path(__file__).with_name("assistant_cases.json")
# Never shown to users: parts of the agents' instructions and tool names.
LEAK_PATTERNS = [r"AIza[0-9A-Za-z_\-]{10,}", r"read_conversation|submit_answer|submit_plan|submit_itinerary",
                 r"inspect_trip|inspect_request", r"untrusted DATA"]


def fill_dates(text, today=None):
    """'{d+5}' -> the date 5 days from today as dd/mm."""
    today = today or date.today()
    return re.sub(r"\{d\+(\d+)\}", lambda m: (today + timedelta(days=int(m.group(1)))).strftime("%d/%m"), text)


def load_cases(path=CASES, today=None):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))["cases"]
    return json.loads(fill_dates(json.dumps(raw, ensure_ascii=False), today))


def grade(expect, replies, slots, secrets=()):
    """Failed checks (Vietnamese, one line each) for the last turn's replies; [] means passed."""
    failed = []
    agents = [r.agent for r in replies]
    text = "\n".join(r.text for r in replies)
    places = [p for r in replies for p in (r.places or [])]
    plans = [r.plan for r in replies if r.plan is not None]
    if "agents" in expect and agents != expect["agents"]:
        failed.append(f"chuyên gia {agents}, cần {expect['agents']}")
    if "agent_in" in expect and not set(agents) & set(expect["agent_in"]):
        failed.append(f"chuyên gia {agents}, cần một trong {expect['agent_in']}")
    if expect.get("not_failed", True) and any(r.failed for r in replies):
        failed.append("câu trả lời báo lỗi")
    if len(places) < expect.get("min_places", 0):
        failed.append(f"{len(places)} địa điểm, cần ít nhất {expect['min_places']}")
    if "place_matches" in expect and not any(re.search(expect["place_matches"], p.name, re.I) for p in places):
        failed.append(f"không địa điểm nào khớp “{expect['place_matches']}”")
    if expect.get("citations") and not any(r.citations for r in replies):
        failed.append("không có trích dẫn nguồn")
    if "plan_days" in expect:
        days = len(plans[-1].draft.days) if plans else 0
        if days != expect["plan_days"]:
            failed.append(f"lịch {days} ngày, cần {expect['plan_days']}")
    if "budget_verdict" in expect:
        verdict = plans[-1].budget.verdict if plans else None
        if verdict != expect["budget_verdict"]:
            failed.append(f"chi phí “{verdict}”, cần “{expect['budget_verdict']}”")
    for pattern in expect.get("text_any", []):
        if not re.search(pattern, text, re.I):
            failed.append(f"câu trả lời thiếu “{pattern}”")
    for pattern in expect.get("text_none", []):
        if re.search(pattern, text, re.I):
            failed.append(f"câu trả lời có “{pattern}” (không được có)")
    for key, value in expect.get("slots", {}).items():
        if getattr(slots, key, None) != value:
            failed.append(f"{key} = {getattr(slots, key, None)!r}, cần {value!r}")
    for pattern in LEAK_PATTERNS + [re.escape(s) for s in secrets if s]:
        if re.search(pattern, text):
            failed.append("lộ thông tin nội bộ")
            break
    return failed


async def run_case(service, case, secrets=(), timeout=300):
    """Run one case in a fresh session; returns a result row."""
    session_id, replies, router, error = None, [], [], None
    original = service.route

    async def recording_route(session, text, context):
        decision, how = await original(session, text, context)
        router.append(how)
        return decision, how

    service.route = recording_route
    started = time.monotonic()
    try:
        for text in case["turns"]:
            session, replies = await asyncio.wait_for(service.handle_turn(session_id, text), timeout)
            session_id = session.id
        failed = grade(case["expect"], replies, session.slots, secrets)
    except Exception as exc:  # a crash or timeout is a failed case, not a stopped run
        error, failed = type(exc).__name__, [f"lỗi khi chạy: {type(exc).__name__}"]
    finally:
        service.route = original
    return {
        "id": case["id"], "category": case["category"], "passed": not failed, "failed": failed,
        "agents": [r.agent for r in replies], "router": router[-1] if router else None,
        "seconds": round(time.monotonic() - started, 1), "error": error,
        "answer": "\n".join(r.text for r in replies)[:600],
    }


async def evaluate(service, cases, secrets=(), pause_s=0.0, on_row=None, retry_after_s=None):
    """Run cases one after another (the free Gemini quota is per minute); returns the rows.

    retry_after_s: wait that long, then run every failed case once more. Free sources (Gemini,
    the map server) refuse requests for a minute now and then; a case that passes on the second
    try is marked retried, so a flaky source is told apart from a wrong answer.
    """
    rows = []
    for i, case in enumerate(cases):
        if i and pause_s:
            await asyncio.sleep(pause_s)
        row = await run_case(service, case, secrets)
        rows.append(row)
        if on_row:
            on_row(row)
    failed = [i for i, row in enumerate(rows) if not row["passed"]]
    if retry_after_s is not None and failed:
        await asyncio.sleep(retry_after_s)
        by_id = {c["id"]: c for c in cases}
        for i in failed:
            again = await run_case(service, by_id[rows[i]["id"]], secrets)
            again["retried"], again["first_failed"] = True, rows[i]["failed"]
            rows[i] = again
            if on_row:
                on_row(again)
    return rows


def summary(rows):
    """{category: (passed, total)} plus 'Tổng'."""
    out = {}
    for row in rows:
        ok, total = out.get(row["category"], (0, 0))
        out[row["category"]] = (ok + row["passed"], total + 1)
    out["Tổng"] = (sum(r["passed"] for r in rows), len(rows))
    return out


def markdown(rows, model):
    lines = [f"# Đánh giá Trợ lý AI ({model})", "", "| Nhóm | Đạt | Tỉ lệ |", "|---|---|---|"]
    for category, (ok, total) in summary(rows).items():
        name = f"**{category}**" if category == "Tổng" else category
        lines.append(f"| {name} | {ok}/{total} | {ok / total:.0%} |")
    llm = sum(r["router"] == "llm" for r in rows)
    lines += ["", f"Lễ tân dùng Gemini ở {llm}/{len(rows)} hội thoại; còn lại định tuyến theo từ khoá vì Gemini lỗi.",
              "", "| Mã | Nhóm | Kết quả | Chuyên gia | Giây | Lỗi |", "|---|---|---|---|---|---|"]
    retried = [r for r in rows if r.get("retried") and r["passed"]]
    if retried:
        at = lines.index("") + 1  # after the title, before the score table, with a blank line between
        lines[at:at] = [f"{len(retried)} ca chỉ đạt ở lần chạy lại (nguồn miễn phí tạm từ chối yêu cầu ở lần đầu): "
                        + ", ".join(r["id"] for r in retried) + ".", ""]
    for r in rows:
        result = "✅" if r["passed"] else "❌"
        if r.get("retried") and r["passed"]:
            result = "✅ (lần 2)"
        reason = "; ".join(r["failed"] or (["lần 1: " + "; ".join(r["first_failed"])] if r.get("retried") else []))
        lines.append(f"| {r['id']} | {r['category']} | {result} | {', '.join(r['agents'])} | {r['seconds']} | {reason} |")
    return "\n".join(lines) + "\n"
