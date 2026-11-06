"""Opt-in live evaluation of the LLM Place Agent on both engines; not part of the unit suite.

Needs GOOGLE_API_KEY in .env, network access, and the ai + maf extras:
    uv run python scripts/eval_place_agent.py --runs 1

Calls real Gemini and Photon/OpenStreetMap. Writes evaluation/place-agent-eval-<UTC>/.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluation.place_agent_eval import evaluate, markdown  # noqa: E402
from app.specialists.api import SpecialistSettings, gemini_factory, maf_gemini_factory  # noqa: E402
from app.tools.places.geo_places import GeoPlaceService  # noqa: E402


async def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    settings = SpecialistSettings(travelmate_api_token="unused-by-this-script")
    if not settings.google_api_key.get_secret_value():
        raise SystemExit("Configure GOOGLE_API_KEY in .env first")
    cases = json.loads(args.cases.read_text("utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    async with gemini_factory(settings) as adk, maf_gemini_factory(settings) as maf:
        report = await evaluate(
            cases, {"adk": adk, "maf": maf}, GeoPlaceService(), runs=args.runs, pause_s=args.pause
        )
    report |= {"model": settings.gemini_model, "created_at": datetime.now(UTC).isoformat()}
    out = ROOT / "evaluation" / f"place-agent-eval-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    (out / "REPORT.md").write_text(markdown(report, settings.gemini_model), "utf-8")
    print(markdown(report, settings.gemini_model))
    print(f"Saved to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--cases", type=Path, default=ROOT / "examples" / "eval" / "place_cases.json")
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--pause", type=float, default=8.0, help="seconds between runs (avoid source throttling)")
    asyncio.run(main(parser.parse_args()))
