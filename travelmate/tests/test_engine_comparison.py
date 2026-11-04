import json

import pytest

pytest.importorskip("google.adk")
pytest.importorskip("agent_framework")
from test_adk_tools import ScriptedModel, fixture_data
from test_maf_tools import ScriptedClient

from app.adk_adapter import AdkPlanner
from app.engine_comparison import compare, markdown
from app.maf_adapter import MafPlanner


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
            "adk": (AdkPlanner, lambda: ScriptedModel(calls=good)),
            "maf": (MafPlanner, lambda: ScriptedClient([])),  # text only: never accepted
        },
        runs=2,
    )
    assert report["summary"]["adk"]["accepted"] == 2 and report["summary"]["adk"]["accept_rate"] == 1.0
    assert report["summary"]["maf"]["accepted"] == 0
    assert report["summary"]["maf"]["errors"] == {"AgentError": 2}
    assert [r["engine"] for r in report["runs"]] == ["adk", "maf", "adk", "maf"]
    dumped = json.dumps(report)
    assert "demo-attraction" not in dumped and "draft" not in dumped
    table = markdown(report, "test-model")
    assert "| adk | 2 | 2 | 100% |" in table and "| maf | 2 | 0 | 0% |" in table
