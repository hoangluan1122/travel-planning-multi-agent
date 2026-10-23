import json
from pathlib import Path

import pytest

from app.evaluate_routes import evaluate
from app.specialists.routing import RouteMatrix, RouteRequest


def test_live_snapshot_replays_without_network():
    path = Path(__file__).parents[1] / "evaluation/routes-live-2026-10-21.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert len(snapshot["cases"]) == 6
    for case in snapshot["cases"]:
        result = evaluate(
            RouteRequest.model_validate(case["request"]),
            RouteMatrix.model_validate(case["optimized"]["matrix"]),
        )
        actual = result["optimized"]
        assert actual["status"] == case["optimized"]["status"]
        if actual["status"] == "feasible":
            assert actual["travel_seconds"] == pytest.approx(case["optimized"]["travel_seconds"])
            assert actual["travel_seconds"] <= result["nearest_neighbor_seconds"] + 1e-8
            ids = [v["place_id"] for v in actual["schedule"]]
            assert set(ids) == {v["id"] for v in case["request"]["visits"]}
        else:
            assert actual["schedule"] == []
