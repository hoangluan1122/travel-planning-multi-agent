from datetime import date
from app.agents import PlannerAgent
from app.schemas import TripRequest


def test_plan_contains_one_day_per_requested_date():
    request = TripRequest(destination="Đà Nẵng", start_date=date(2026, 9, 10), end_date=date(2026, 9, 12), budget=5_000_000, interests=["biển"])
    plan = PlannerAgent().plan(request)
    assert len(plan.itinerary) == 3
    assert plan.estimated_cost <= request.budget
