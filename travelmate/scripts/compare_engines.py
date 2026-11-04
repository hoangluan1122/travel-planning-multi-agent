"""Opt-in live comparison of the ADK and MAF planner engines; never part of the unit suite.

Needs GOOGLE_API_KEY in .env and both extras:
    uv sync --extra dev --extra ai --extra maf
    uv run python scripts/compare_engines.py --runs 3

Calls the real Gemini API (costs tokens). Writes evaluation/engine-comparison-<UTC>/
with report.json and REPORT.md.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adk_adapter import AdkPlanner  # noqa: E402
from app.engine_comparison import compare, markdown  # noqa: E402
from app.maf_adapter import MafPlanner  # noqa: E402
from app.models import PlannerInput  # noqa: E402
from app.specialist_api import SpecialistSettings, gemini_factory, maf_gemini_factory  # noqa: E402


async def main(args):
    # Windows consoles default to cp1252, which cannot print the Vietnamese report.
    sys.stdout.reconfigure(encoding="utf-8")
    settings = SpecialistSettings(travelmate_api_token="unused-by-this-script")
    if not settings.google_api_key.get_secret_value():
        raise SystemExit("Configure GOOGLE_API_KEY in .env first")
    cases = {path.stem: PlannerInput.model_validate_json(path.read_text("utf-8-sig")) for path in args.input}
    async with gemini_factory(settings) as adk_factory, maf_gemini_factory(settings) as maf_factory:
        report = await compare(
            cases,
            {"adk": (AdkPlanner, adk_factory), "maf": (MafPlanner, maf_factory)},
            runs=args.runs,
            timeout=args.timeout,
        )
    report["model"] = settings.gemini_model
    report["created_at"] = datetime.now(UTC).isoformat()
    out = ROOT / "evaluation" / f"engine-comparison-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    (out / "REPORT.md").write_text(markdown(report, settings.gemini_model), "utf-8")
    print(markdown(report, settings.gemini_model))
    print(f"Saved to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--input", type=Path, nargs="+", default=[ROOT / "examples" / "planner.json"])
    asyncio.run(main(parser.parse_args()))
