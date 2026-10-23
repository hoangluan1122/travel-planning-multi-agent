"""Small live routing benchmark; prints reproducible evidence, never a quality certification."""

import asyncio
import json
import random
import sys
from datetime import UTC, datetime

from .specialists.routing import OSRMProvider, RouteRequest, optimize, schedule_order


def nearest_order(matrix):
    remaining = set(range(1, len(matrix.point_ids)))
    order, current = [], 0
    while remaining:
        reachable = [i for i in remaining if matrix.durations_seconds[current][i] is not None]
        if not reachable:
            return None
        current = min(reachable, key=lambda i: (matrix.durations_seconds[current][i], i))
        order.append(current)
        remaining.remove(current)
    return order


def evaluate(request, matrix):
    report = optimize(request, matrix)
    nearest = nearest_order(matrix)
    nearest_schedule = schedule_order(request, matrix, nearest) if nearest else None
    rng = random.Random(42)
    trials = []
    for _ in range(20):
        order = list(range(1, len(request.visits) + 1))
        rng.shuffle(order)
        schedule = schedule_order(request, matrix, order)
        trials.append(schedule[0] if schedule else None)
    feasible = [v for v in trials if v is not None]
    return {
        "request": request.model_dump(mode="json"),
        "optimized": report.model_dump(mode="json"),
        "nearest_neighbor_seconds": nearest_schedule[0] if nearest_schedule else None,
        "random_seed": 42,
        "random_trials": trials,
        "random_feasible_count": len(feasible),
        "random_mean_seconds": sum(feasible) / len(feasible) if feasible else None,
    }


async def main():
    cases = {
        "danang": [(16.0678, 108.2208), (16.0472, 108.2244), (16.0795, 108.2240), (16.0590, 108.2450)],
        "hanoi": [(21.0285, 105.8542), (21.0358, 105.8345), (21.0245, 105.8412), (21.0300, 105.8520)],
        "hcmc": [(10.7766, 106.7009), (10.7725, 106.6980), (10.7798, 106.6990), (10.7820, 106.6920)],
    }
    provider = OSRMProvider()
    results = []
    for name, points in cases.items():
        request = RouteRequest(
            origin={"id": "origin", "latitude": points[0][0], "longitude": points[0][1]},
            visits=[
                {"id": f"stop-{i}", "latitude": p[0], "longitude": p[1], "duration_minutes": 45}
                for i, p in enumerate(points[1:], 1)
            ],
        )
        try:
            matrix = await provider.matrix([request.origin, *request.visits])
            for variant in ["normal", "tight"]:
                case = request.model_copy(deep=True)
                if variant == "tight":
                    case.finish_by_minute = 550
                results.append({"case": f"{name}-{variant}", **evaluate(case, matrix)})
        except Exception as exc:
            results.append({"case": name, "error_type": type(exc).__name__})
        await asyncio.sleep(1)  # Small, sequential sample; do not load-test a public demo server.
    print(
        json.dumps(
            {
                "evaluated_at": datetime.now(UTC).isoformat(),
                "cases": results,
                "limitations": [
                    "Road-network estimates, not observed travel times",
                    "Coordinate samples, not verified attraction entrances",
                    "No live Gemini evaluation or human usability evaluation",
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
