"""Opt-in live check: the LLM Place Agent on ADK and on MAF, real Gemini + real place sources.

Needs GOOGLE_API_KEY in .env, network access, and both extras:
    uv run python scripts/verify_live_place_engines.py

Runs each (destination, category) once per engine through LivePlaceAgent, the same path
as LIVE_PLACE_MODE=adk_llm / maf_llm. Records status, counts and latency only; place
names stay in the report because they are public source data, not user input.
Writes evaluation/live-place-engines-<UTC>/.
"""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Context  # noqa: E402
from app.place_agent.live import LivePlaceAgent, LivePlaceRequest  # noqa: E402
from app.specialists.api import SpecialistSettings, agent_model_factory  # noqa: E402
from app.tools.places.geo_places import GeoPlaceService  # noqa: E402

CASES = [("Hội An", "restaurant"), ("Sa Pa", "hotel"), ("Đà Lạt", "attraction")]


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    settings = SpecialistSettings(travelmate_api_token="unused-by-this-script")
    if not settings.google_api_key.get_secret_value():
        raise SystemExit("Configure GOOGLE_API_KEY in .env first")
    geo = GeoPlaceService()
    rows = []
    for destination, category in CASES:
        for engine in ["adk", "maf"]:
            started = time.monotonic()
            row = {"engine": engine, "destination": destination, "category": category}
            try:
                # Ambiguous names stop at needs_location before any LLM call; pick the top
                # option the way a user would click it in the UI, and record the choice.
                request = LivePlaceRequest(destination=destination, category=category, limit=5)
                resolved = await LivePlaceAgent(geo_service=geo).run(request, Context(), 60)
                if resolved.status == "needs_location" and resolved.location_options:
                    choice = resolved.location_options[0]
                    row["chosen_location"] = {"id": choice.id, "name": choice.name, "admin1": choice.admin1}
                    request = request.model_copy(update={"location_id": choice.id})
                async with agent_model_factory(settings, engine) as factory:
                    report = await LivePlaceAgent(model_factory=factory, geo_service=geo, engine=engine).run(
                        request, Context(), 140
                    )
                row |= {
                    "status": report.status,
                    "execution_mode": report.execution_mode,
                    "places": len(report.places),
                    "search_calls": report.search_calls,
                    "detail_calls": report.detail_calls,
                    "place_names": [p.name for p in report.places],
                }
            except Exception as exc:  # record, keep going
                row |= {"status": "exception", "error_type": type(exc).__name__}
            row["duration_ms"] = int((time.monotonic() - started) * 1000)
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "place_names"}, ensure_ascii=False))
    out = ROOT / "evaluation" / f"live-place-engines-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    payload = {"model": settings.gemini_model, "created_at": datetime.now(UTC).isoformat(), "runs": rows}
    (out / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
