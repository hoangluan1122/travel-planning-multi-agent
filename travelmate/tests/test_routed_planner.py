from datetime import UTC, datetime

import pytest

from app.models import Draft
from app.specialists.routed_planner import RoutedPlannerInput, route_draft
from app.specialists.routing import RouteMatrix


@pytest.mark.asyncio
@pytest.mark.parametrize("finish,status", [(1080, "route_feasible_draft"), (550, "infeasible")])
async def test_routed_plan_preserves_visits_and_exposes_infeasibility(finish, status):
    from test_adk_tools import fixture_data

    data, draft = await fixture_data()
    request = RoutedPlannerInput(
        **data.model_dump(),
        route_days=[
            {
                "date": day["date"],
                "origin": {"id": "origin", "latitude": 16, "longitude": 108},
                "finish_by_minute": finish,
            }
            for day in draft["days"]
        ],
    )

    class Provider:
        async def matrix(self, points):
            return RouteMatrix(
                point_ids=[p.id for p in points],
                durations_seconds=[[0, 60], [60, 0]],
                source="fixture",
                fetched_at=datetime.now(UTC),
            )

    result = await route_draft(request, Draft.model_validate(draft), Provider())
    assert result.status == status
    assert result.original_draft == Draft.model_validate(draft)
    if status == "route_feasible_draft":
        assert result.days[0].route.schedule[0].place_id == "demo-attraction"
        assert result.days[0].route.schedule[0].start_second >= 541 * 60
    else:
        assert result.days[0].route.schedule == []


@pytest.mark.asyncio
async def test_routing_preserves_general_schedule_window():
    from test_adk_tools import fixture_data

    from app.models import ScheduleConstraints

    data, draft = await fixture_data()
    data.constraints = ScheduleConstraints(
        day_start_minute=540,
        day_end_minute=700,
        visit_windows={
            "demo-attraction": {"opens_minute": 540, "closes_minute": 680, "source": "user-supplied window"}
        },
    )
    request = RoutedPlannerInput(
        **data.model_dump(),
        route_days=[
            {
                "date": day["date"],
                "origin": {"id": "origin", "latitude": 16, "longitude": 108},
                "departure_minute": 480,
            }
            for day in draft["days"]
        ],
    )

    class Provider:
        async def matrix(self, points):
            return RouteMatrix(
                point_ids=[p.id for p in points],
                durations_seconds=[[0, 60], [60, 0]],
                source="fixture",
                fetched_at=datetime.now(UTC),
            )

    result = await route_draft(request, Draft.model_validate(draft), Provider())
    assert result.status == "route_feasible_draft"
    for day in result.days:
        assert day.route.schedule[0].start_second >= 540 * 60
        assert day.route.schedule[0].end_second <= 680 * 60
        assert day.unverified_window_ids == []
        assert day.supplied_window_sources["demo-attraction"] == "user-supplied window"


@pytest.mark.asyncio
async def test_routed_planner_keeps_appointment_buffer_and_separate_endpoint():
    from test_adk_tools import fixture_data

    data, draft = await fixture_data()
    request = RoutedPlannerInput(
        **data.model_dump(),
        route_days=[
            {
                "date": day["date"],
                "origin": {"id": "hotel", "latitude": 16, "longitude": 108},
                "destination": {"id": "airport", "latitude": 16.1, "longitude": 108.1},
                "return_to_origin": False,
                "travel_buffer_minutes": 5,
                "fixed_starts": {"demo-attraction": 700},
            }
            for day in draft["days"]
        ],
    )

    class Provider:
        async def matrix(self, points):
            n = len(points)
            return RouteMatrix(
                point_ids=[p.id for p in points],
                durations_seconds=[[0 if i == j else 60 for j in range(n)] for i in range(n)],
                source="fixture",
                fetched_at=datetime.now(UTC),
            )

    result = await route_draft(request, Draft.model_validate(draft), Provider())
    assert result.status == "route_feasible_draft"
    for day in result.days:
        assert day.route.schedule[0].start_second == 700 * 60
        assert day.route.buffer_seconds == 600
        assert day.route.legs[-1].to_id == "airport"
