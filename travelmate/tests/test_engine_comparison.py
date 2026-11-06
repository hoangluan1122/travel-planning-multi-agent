import json

import pytest

pytest.importorskip("google.adk")
pytest.importorskip("agent_framework")
from test_adk_tools import ScriptedModel, fixture_data
from test_maf_tools import ScriptedClient

from app.evaluation.engine_comparison import compare, markdown


@pytest.mark.asyncio
async def test_comparison_reports_outcomes_per_engine_without_content():
    data, draft = await fixture_data()
    good = [
        {"name": "inspect_trip", "args": {}},
        {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
    ]
    report = await compare(
        {"fixture": data},
        {
            "adk": lambda: ScriptedModel(calls=good),
            "maf": lambda: ScriptedClient([]),  # text only: never accepted
        },
        runs=2,
    )
    assert report["summary"]["adk"]["accepted"] == 2 and report["summary"]["adk"]["accept_rate"] == 1.0
    assert report["summary"]["maf"]["accepted"] == 0
    assert report["summary"]["maf"]["errors"] == {"AgentError": 2}
    assert [r["engine"] for r in report["runs"]] == ["adk", "maf", "adk", "maf"]
    dumped = json.dumps(report)
    assert "demo-attraction" not in dumped and "draft" not in dumped
    assert {r["agent"] for r in report["runs"]} == {"planner_specialist"}
    table = markdown(report, "test-model")
    assert "| adk | 2 | 2 | 100% |" in table and "| maf | 2 | 0 | 0% |" in table


@pytest.mark.asyncio
async def test_recommendation_cases_run_on_both_engines():
    from test_agent_contracts import place

    from app.specialists.recommendation import RecommendationRequest

    calls = [
        {"name": "inspect_candidates", "args": {}},
        {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
    ]
    report = await compare(
        {"rec": RecommendationRequest(candidates=[place("p1"), place("p2")], limit=1)},
        {"adk": lambda: ScriptedModel(calls=calls), "maf": lambda: ScriptedClient(calls)},
        runs=1,
    )
    assert report["summary"]["adk"]["accepted"] == report["summary"]["maf"]["accepted"] == 1
    assert {r["agent"] for r in report["runs"]} == {"recommendation_specialist"}
    assert set(report["by_case"]) == {"rec · adk", "rec · maf"}
