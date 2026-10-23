import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import Context
from app.specialists.trip_budget import TripBudgetRequest, TripBudgetSpecialist, assess_trip_budget

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def example():
    return json.loads((Path(__file__).parents[1] / "examples/trip-budget.json").read_text(encoding="utf-8"))


async def evaluate(raw):
    return await TripBudgetSpecialist(now=lambda: NOW).run(TripBudgetRequest.model_validate(raw), Context())


@pytest.mark.asyncio
async def test_group_trip_counts_and_proposal_are_auditable():
    data = example()
    report = await evaluate(data)
    assert (report.days, report.nights, report.travelers, report.rooms) == (3, 2, 2, 1)
    by_id = {line.expense_id: line for line in report.lines}
    assert by_id["hotel"].quantity == 2  # room-nights, not people-nights
    assert by_id["food"].quantity == 18  # 2 people × 3 days × 3 meals
    assert by_id["transport"].quantity == 1  # group charge, not per person
    assert report.known_min_vnd == report.known_max_vnd == Decimal("3700000")
    assert report.reserve_vnd == Decimal("370000")
    assert report.known_max_with_reserve_vnd == Decimal("4070000")
    assert report.status == "at_risk" and report.over_budget_vnd == Decimal("70000")
    assert report.proposal.status == "fits_supplied_costs"
    assert report.proposal.changes[0].proposed_option_id == "economy"
    assert report.proposal.proposed_max_with_reserve_vnd == Decimal("3850000")
    assert report.proposal.savings_with_reserve_vnd == Decimal("220000")
    assert report.proposal.applied is False
    assert data["expenses"][0]["selected_option_id"] == "standard"
    assert sum(report.category_known_max_vnd.values()) == report.known_max_vnd


@pytest.mark.asyncio
async def test_per_person_cap_and_odd_party_rooms():
    data = example()
    data.update(travelers=3, budget_scope="per_person", budget_vnd="3000000")
    report = await evaluate(data)
    assert report.rooms == 2 and report.group_budget_vnd == Decimal("9000000")
    assert report.lines[0].quantity == 4
    assert report.lines[1].quantity == 27
    assert report.status == "within_estimate" and report.proposal is None


@pytest.mark.asyncio
async def test_unknown_is_null_not_free_and_incomplete_even_with_positive_balance():
    data = example()
    option = data["expenses"][2]["options"][0]
    option.update(min_unit_price_vnd=None, max_unit_price_vnd=None, certainty="unknown")
    report = await evaluate(data)
    assert report.status == "incomplete" and not report.coverage_complete
    assert report.unknown_expense_ids == ["transport"]
    assert report.lines[2].max_total_vnd is None
    assert report.known_max_vnd == Decimal("3200000")


@pytest.mark.asyncio
async def test_partial_known_costs_can_already_exceed_cap():
    data = example()
    data["budget_vnd"] = "1000000"
    data["expenses"] = data["expenses"][:2]
    report = await evaluate(data)
    assert report.status == "over_budget" and not report.coverage_complete
    assert set(report.missing_categories) == {"transport", "visits"}
    assert report.proposal.status == "still_over_budget"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["expired", "future_observation", "outside_service_dates"])
async def test_unusable_quotes_excluded_and_explained(reason):
    data = example()
    option = data["expenses"][0]["options"][0]
    option.update(certainty="quoted", observed_at=(NOW - timedelta(hours=1)).isoformat())
    if reason == "expired":
        option["valid_until"] = NOW.isoformat()
    elif reason == "future_observation":
        option["observed_at"] = (NOW + timedelta(days=1)).isoformat()
    else:
        option.update(service_start_date="2026-11-06", service_end_date="2026-11-06")
    report = await evaluate(data)
    assert report.lines[0].price_state == reason
    assert report.lines[0].max_total_vnd is None
    assert report.status == "incomplete"
    assert report.proposal is None  # Unknown selected expense cannot yield a claimed saving.


@pytest.mark.asyncio
async def test_one_day_trip_has_no_room_nights_or_required_accommodation():
    data = example()
    data["end_date"] = data["start_date"]
    report = await evaluate(data)
    assert report.nights == 0 and report.days == 1
    assert report.lines[0].quantity == 0 and report.lines[0].price_state == "not_applicable"
    assert report.lines[0].max_total_vnd == Decimal("0")
    assert report.coverage_complete


@pytest.mark.asyncio
async def test_explicit_dates_and_exact_whole_vnd_rounding():
    data = example()
    data["expenses"] = [data["expenses"][1]]
    data["required_categories"] = ["meals"]
    data["expenses"][0]["dates"] = ["2026-11-07"]
    data["expenses"][0]["options"][0].update(min_unit_price_vnd="0.10", max_unit_price_vnd="0.10")
    report = await evaluate(data)
    assert report.lines[0].quantity == 6
    assert report.known_max_vnd == Decimal("1")
    assert report.reserve_vnd == Decimal("1")


@pytest.mark.asyncio
async def test_price_range_worst_case_and_exact_cap_boundary():
    data = example()
    data.update(reserve_pct="0", budget_vnd="3700000")
    assert (await evaluate(data)).status == "within_estimate"
    data["expenses"][0]["options"][0]["max_unit_price_vnd"] = "600000"
    report = await evaluate(data)
    assert report.known_min_vnd == Decimal("3700000")
    assert report.known_max_vnd == Decimal("3900000") and report.status == "at_risk"


@pytest.mark.asyncio
async def test_optional_drop_requires_flag_and_exposes_missing_required_category():
    data = example()
    data["expenses"] = [data["expenses"][-1]]
    data["expenses"][0]["required"] = False
    data.update(budget_vnd="1", required_categories=["visits"])
    assert (await evaluate(data)).proposal.changes == []
    data["allow_drop_optional"] = True
    report = await evaluate(data)
    assert report.proposal.changes[0].action == "drop_optional"
    assert report.proposal.status == "incomplete" and report.proposal.missing_categories == ["visits"]


@pytest.mark.asyncio
async def test_required_items_cannot_be_dropped_and_missing_price_cannot_be_cheaper():
    data = example()
    data.update(budget_vnd="1", allow_drop_optional=True)
    data["expenses"][0]["options"][1].update(
        min_unit_price_vnd=None,
        max_unit_price_vnd=None,
        certainty="unknown",
    )
    report = await evaluate(data)
    assert report.proposal.changes == [] and report.proposal.status == "still_over_budget"


@pytest.mark.asyncio
async def test_largest_independent_saving_minimizes_number_of_changed_items():
    data = example()
    # Hotel saves 200k; transport alternative saves 400k. Only one change is needed.
    data["budget_vnd"] = "3700000"
    data["expenses"][2]["options"].append(
        {
            "id": "bus",
            "label": "Acceptable alternative fixture",
            "billing_unit": "group",
            "min_unit_price_vnd": "100000",
            "max_unit_price_vnd": "100000",
            "certainty": "estimated",
            "source": "fixture",
        }
    )
    report = await evaluate(data)
    assert len(report.proposal.changes) == 1
    assert report.proposal.changes[0].expense_id == "transport"
    assert report.proposal.proposed_max_with_reserve_vnd == Decimal("3630000")
    assert report.proposal.status == "fits_supplied_costs"


@pytest.mark.asyncio
async def test_unpriced_cost_prevents_proposal_from_claiming_trip_fits():
    data = example()
    data["budget_vnd"] = "3000000"
    data["expenses"][2]["options"][0].update(
        certainty="unknown",
        min_unit_price_vnd=None,
        max_unit_price_vnd=None,
    )
    data["expenses"][0]["options"][1].update(min_unit_price_vnd="100000", max_unit_price_vnd="100000")
    report = await evaluate(data)
    assert report.proposal.proposed_max_with_reserve_vnd == Decimal("2640000")
    assert report.proposal.status == "incomplete"


@pytest.mark.asyncio
async def test_outdated_alternative_cannot_make_proposal_cheaper():
    data = example()
    data["expenses"][0]["options"][1].update(
        observed_at=(NOW - timedelta(days=2)).isoformat(),
        valid_until=(NOW - timedelta(days=1)).isoformat(),
    )
    report = await evaluate(data)
    assert report.proposal.changes == [] and report.proposal.status == "still_over_budget"


@pytest.mark.asyncio
async def test_empty_input_and_zero_cost_have_different_coverage():
    data = example()
    data["expenses"] = []
    report = await evaluate(data)
    assert report.status == "incomplete" and report.known_max_vnd == 0
    data["required_categories"] = ["visits"]
    data["expenses"] = [example()["expenses"][-1]]
    data["expenses"][0]["options"][0].update(min_unit_price_vnd="0", max_unit_price_vnd="0")
    assert (await evaluate(data)).status == "within_estimate"


@pytest.mark.parametrize(
    "case",
    [
        "negative",
        "reversed_range",
        "bool_people",
        "bool_drop",
        "unknown_has_price",
        "duplicate_expense",
        "duplicate_option",
        "unknown_selection",
        "too_few_rooms",
        "date_outside",
        "night_on_checkout",
        "naive_timestamp",
        "quoted_without_timestamp",
    ],
)
def test_invalid_inputs(case):
    data = example()
    option = data["expenses"][0]["options"][0]
    if case == "negative":
        option["min_unit_price_vnd"] = "-1"
    elif case == "reversed_range":
        option["min_unit_price_vnd"] = "999999"
    elif case == "bool_people":
        data["travelers"] = True
    elif case == "bool_drop":
        data["allow_drop_optional"] = "yes"
    elif case == "unknown_has_price":
        option["certainty"] = "unknown"
    elif case == "duplicate_expense":
        data["expenses"].append(data["expenses"][0])
    elif case == "duplicate_option":
        data["expenses"][0]["options"].append(option)
    elif case == "unknown_selection":
        data["expenses"][0]["selected_option_id"] = "invented"
    elif case == "too_few_rooms":
        data.update(rooms=1, travelers=3)
    elif case == "date_outside":
        data["expenses"][0]["dates"] = ["2026-11-01"]
    elif case == "night_on_checkout":
        data["expenses"][0]["dates"] = [data["end_date"]]
    elif case == "naive_timestamp":
        option["observed_at"] = "2026-10-21T00:00:00"
    elif case == "quoted_without_timestamp":
        option["certainty"] = "quoted"
    with pytest.raises(ValidationError):
        TripBudgetRequest.model_validate(data)


@pytest.mark.asyncio
async def test_runtime_revalidates_mutation():
    data = TripBudgetRequest.model_validate(example())
    data.expenses[0].options[0].min_unit_price_vnd = Decimal("-1")
    with pytest.raises(ValidationError):
        await TripBudgetSpecialist().run(data, Context())


@pytest.mark.asyncio
async def test_adk_callable_returns_same_deterministic_amounts():
    result = await assess_trip_budget(json.dumps(example()))
    assert result["known_max_with_reserve_vnd"] == "4070000"
    assert result["proposal"]["applied"] is False


def test_trip_budget_api_auth_schema_and_result():
    from fastapi.testclient import TestClient

    from app.specialist_api import SpecialistSettings, create_app

    with TestClient(create_app(SpecialistSettings(travelmate_api_token="test-token"))) as client:
        path = "/api/v1/agents/budget/trip"
        assert client.post(path, json=example()).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        response = client.post(path, headers=headers, json=example())
        assert response.status_code == 200
        assert response.json()["known_max_with_reserve_vnd"] == "4070000"
        bad = example()
        bad["travelers"] = True
        assert client.post(path, headers=headers, json=bad).status_code == 422
