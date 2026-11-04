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

from app.engine_comparison import compare, markdown  # noqa: E402
from app.models import PlannerInput  # noqa: E402
from app.specialist_api import SpecialistSettings, gemini_factory, maf_gemini_factory  # noqa: E402
from app.specialists.recommendation import RecommendationRequest  # noqa: E402


def load_case(path):
    """A file with "trip" is a planner case; one with "candidates" a recommendation case."""
    raw = path.read_text("utf-8-sig")
    return (PlannerInput if '"trip"' in raw else RecommendationRequest).model_validate_json(raw)


async def main(args):
    # Windows consoles default to cp1252, which cannot print the Vietnamese report.
    sys.stdout.reconfigure(encoding="utf-8")
    settings = SpecialistSettings(travelmate_api_token="unused-by-this-script")
    if not settings.google_api_key.get_secret_value():
        raise SystemExit("Configure GOOGLE_API_KEY in .env first")
    cases = {path.stem: load_case(path) for path in args.input}
    async with gemini_factory(settings) as adk_factory, maf_gemini_factory(settings) as maf_factory:
        report = await compare(
            cases,
            {"adk": adk_factory, "maf": maf_factory},
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
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[ROOT / "examples" / "planner.json", *sorted((ROOT / "examples" / "compare").glob("*.json"))],
    )
    asyncio.run(main(parser.parse_args()))
