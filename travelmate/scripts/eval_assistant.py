"""Opt-in live evaluation of the AI assistant on graded conversations; not part of the unit suite.

Needs GOOGLE_API_KEY in .env and network access (uses the live settings: Gemini, real places
and weather). About 42 conversations and 150-250 Gemini calls: run it when the free quota is
fresh, and keep --pause so the per-minute limit is not hit.

    uv run python scripts/eval_assistant.py                 # every case
    uv run python scripts/eval_assistant.py --only guide    # cases whose id contains "guide"

Writes evaluation/assistant-eval-<UTC>/ (report.md, results.json); exit code 1 when the pass
rate is below --min-pass.
"""

# Chạy bộ đánh giá Trợ lý AI trên Gemini thật. Chạy tay khi cần (tốn lượt Gemini miễn phí); không nằm
# trong bộ test tự động.

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluation.assistant_eval import evaluate, load_cases, markdown, summary  # noqa: E402
from app.services import build_services  # noqa: E402
from app.settings import Settings  # noqa: E402


async def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    settings = Settings()
    if settings.travelmate_mode != "live" or not settings.google_api_key:
        raise SystemExit("Needs TRAVELMATE_MODE=live and GOOGLE_API_KEY in .env")
    cases = [c for c in load_cases() if not args.only or any(o in c["id"] for o in args.only)]
    service = build_services(settings).chat

    def show(row):
        mark = "✅" if row["passed"] else "❌"
        mark += " (lần 2)" if row.get("retried") else ""
        print(f"{mark} {row['id']:30} {row['router'] or '-':5} {row['seconds']:6}s {'; '.join(row['failed'])}", flush=True)

    rows = await evaluate(service, cases, secrets=[settings.google_api_key, settings.travelmate_api_token],
                          pause_s=args.pause, on_row=show,
                          retry_after_s=args.retry_after if args.retry_after >= 0 else None)
    out = ROOT / "evaluation" / f"assistant-eval-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "report.md").write_text(markdown(rows, settings.gemini_model), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok, total = summary(rows)["Tổng"]
    print(f"\n{ok}/{total} đạt ({ok / total:.0%}). Báo cáo: {out / 'report.md'}")
    return 0 if ok / total >= args.min_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="chỉ chạy các ca có mã chứa một trong các chữ này")
    parser.add_argument("--pause", type=float, default=4.0, help="giây nghỉ giữa hai ca (giới hạn mỗi phút)")
    parser.add_argument("--min-pass", type=float, default=0.8)
    parser.add_argument("--retry-after", type=float, default=65,
                        help="chờ bấy nhiêu giây rồi chạy lại các ca hỏng một lần (âm: không chạy lại)")
    sys.exit(asyncio.run(main(parser.parse_args())))
