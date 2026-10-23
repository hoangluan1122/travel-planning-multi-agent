"""Replay Recommendation over previously fetched real Place records, without network."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .models import Context
from .specialists.recommendation import RecommendationRanker, RecommendationRequest


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.place_snapshot.read_text(encoding="utf-8"))
    data = RecommendationRequest(
        candidates=snapshot["places"],
        interests=["khách sạn", "gia đình"],
        limit=5,
        context={"max_price_vnd": "1500000", "price_basis": "per_room_night"},
    )
    report = await RecommendationRanker().run(data, Context())
    artifact = {
        "verification": "replay_of_real_source_records_not_new_live_search_or_llm_benchmark",
        "place_snapshot": str(args.place_snapshot),
        "request": data.model_dump(mode="json"),
        "result": report.model_dump(mode="json"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report.status,
                "selected": [p.name for p in report.places],
                "missing": [item.missing_evidence for item in report.items],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
