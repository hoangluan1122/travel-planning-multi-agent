from datetime import UTC, datetime

from app.evaluation.place_agent_eval import keywords_from_trace, markdown, summarize
from app.place_agent.live import PlaceTrace


class Report:
    def __init__(self, messages):
        self.trace = [PlaceTrace(step="search", at=datetime.now(UTC), message=m) for m in messages]


def test_keywords_are_read_from_the_trace():
    report = Report(["Phân giải phạm vi Việt Nam", "Từ khoá “chay”. Tra Photon", "Tìm rộng, không từ khoá. Tra"])
    assert keywords_from_trace(report) == ["chay", ""]


def test_summary_and_markdown():
    rows = [
        {"case": "a", "engine": "adk", "status": "success", "places": 5, "grounded": True, "keywords": [""],
         "search_calls": 1, "duration_ms": 1000, "needs_hits": 2},
        {"case": "a", "engine": "maf", "status": "no_results", "places": 0, "grounded": True, "keywords": ["x", ""],
         "search_calls": 2, "duration_ms": 3000},
    ]
    summary = summarize(rows)
    assert summary["adk"]["success_rate"] == 1.0 and summary["adk"]["broad_first_rate"] == 1.0
    assert summary["maf"]["success"] == 0 and summary["maf"]["statuses"] == {"no_results": 1}
    assert summary["adk"]["needs_match_rate"] == 1.0 and summary["adk"]["needs_hit_share"] == 0.4
    assert summary["maf"]["needs_match_rate"] is None  # no expectation for that row
    text = markdown({"summary": summary, "runs": rows}, "m")
    assert "| adk | 1 | 1 | 100% |" in text and "“x”, (rộng)" in text
