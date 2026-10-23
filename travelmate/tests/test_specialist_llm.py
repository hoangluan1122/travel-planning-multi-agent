import json

import pytest

pytest.importorskip("google.adk")
from test_adk_tools import ScriptedModel, fixture_data

from app.agents import AgentError
from app.models import Context, Place
from app.specialists.planner import PlannerSpecialist
from app.specialists.recommendation import RecommendationRequest, RecommendationSpecialist


@pytest.mark.asyncio
async def test_recommendation_repairs_ids_without_rewriting_facts():
    model = ScriptedModel(
        calls=[
            {"name": "inspect_candidates", "args": {}},
            {"name": "submit_ranking", "args": {"place_ids": ["invented"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
        ]
    )
    result = await RecommendationSpecialist(lambda: model).run(
        RecommendationRequest(
            candidates=[
                Place(
                    id="p1",
                    name="Source name",
                    address="Source address",
                    latitude=0,
                    longitude=0,
                    source="fixture",
                )
            ]
        ),
        Context(),
    )
    assert result.places[0].name == "Source name"
    assert any(o.get("accepted") is False for o in model.observations)


@pytest.mark.asyncio
async def test_recommendation_rejects_text_only():
    agent = RecommendationSpecialist(lambda: ScriptedModel(calls=[]))
    with pytest.raises(AgentError):
        await agent.run(
            RecommendationRequest(
                candidates=[
                    Place(id="p1", name="Name", address="Address", latitude=0, longitude=0, source="fixture")
                ]
            ),
            Context(),
        )


@pytest.mark.asyncio
async def test_standalone_planner_uses_supplied_evidence():
    data, draft = await fixture_data()
    agent = PlannerSpecialist(
        lambda: ScriptedModel(
            calls=[
                {"name": "inspect_trip", "args": {}},
                {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
            ]
        )
    )
    result = await agent.run(data, Context())
    assert result.days[0].activities[0].place_id == "demo-attraction"


@pytest.mark.asyncio
async def test_planner_repairs_daily_bounds_and_visit_window():
    from app.models import ScheduleConstraints

    data, draft = await fixture_data()
    data.constraints = ScheduleConstraints(
        day_start_minute=600,
        day_end_minute=900,
        min_activity_minutes=60,
        required_place_ids=["demo-attraction"],
        visit_windows={"demo-attraction": {"opens_minute": 630, "closes_minute": 800, "source": "fixture"}},
    )
    corrected = json.loads(json.dumps(draft))
    for day in corrected["days"]:
        day["activities"][0].update(start_minute=630, end_minute=690)
    model = ScriptedModel(
        calls=[
            {"name": "inspect_trip", "args": {}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(draft)}},
            {"name": "submit_itinerary", "args": {"draft_json": json.dumps(corrected)}},
        ]
    )
    result = await PlannerSpecialist(lambda: model).run(data, Context())
    assert result.days[0].activities[0].start_minute == 630
    assert any(o.get("accepted") is False for o in model.observations)


@pytest.mark.asyncio
async def test_recommendation_cannot_select_excluded_or_omit_required():
    from test_agent_contracts import place

    model = ScriptedModel(
        calls=[
            {"name": "inspect_candidates", "args": {}},
            {"name": "submit_ranking", "args": {"place_ids": ["p2"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p3"]}},
            {"name": "submit_ranking", "args": {"place_ids": ["p1"]}},
        ]
    )
    result = await RecommendationSpecialist(lambda: model).run(
        RecommendationRequest(
            candidates=[place("p1"), place("p2"), place("p3")],
            required_place_ids=["p1"],
            excluded_place_ids=["p2"],
        ),
        Context(),
    )
    assert [p.id for p in result.places] == ["p1"]
    assert any(o.get("error") == "Required places missing" for o in model.observations)


@pytest.mark.asyncio
async def test_recommendation_model_budget_is_domain_error():
    from test_agent_contracts import place

    agent = RecommendationSpecialist(
        lambda: ScriptedModel(
            calls=[
                {"name": "inspect_candidates", "args": {}},
                {"name": "inspect_candidates", "args": {}},
            ]
        ),
        max_llm_calls=1,
    )
    with pytest.raises(AgentError, match="model-call budget"):
        await agent.run(RecommendationRequest(candidates=[place()]), Context())
