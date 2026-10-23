"""Trip-budget assessment and reviewable cost-reduction proposals in VND."""

import math
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ..agents import BaseAgent
from ..models import Context, Model, ShortText

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Category = Literal["accommodation", "meals", "transport", "visits", "other"]
ZERO = Decimal("0")


def dong(value: Decimal) -> Decimal:
    """Round each charge/reserve upward to a whole VND; never underestimate a cap."""
    return value.quantize(Decimal("1"), rounding=ROUND_CEILING)


def aware(value):
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Price timestamps must include a timezone")
    return value


class PriceOption(Model):
    id: ShortText
    label: ShortText
    billing_unit: Literal["person", "room", "group"]
    min_unit_price_vnd: Money | None = None
    max_unit_price_vnd: Money | None = None
    certainty: Literal["quoted", "estimated", "unknown"] = "unknown"
    source: str = Field(min_length=1, max_length=2000)
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    service_start_date: date | None = None
    service_end_date: date | None = None

    _aware = field_validator("observed_at", "valid_until")(aware)

    @model_validator(mode="after")
    def valid_price(self):
        self.source = self.source.strip()
        if not self.source:
            raise ValueError("Price source is required")
        low, high = self.min_unit_price_vnd, self.max_unit_price_vnd
        if self.certainty == "unknown":
            if low is not None or high is not None:
                raise ValueError("Unknown prices must be null")
        elif low is None or high is None or low > high:
            raise ValueError("Known prices require an ordered inclusive range")
        if self.certainty == "quoted" and self.observed_at is None:
            raise ValueError("Quoted prices require an observation timestamp")
        if self.valid_until and self.observed_at and self.valid_until < self.observed_at:
            raise ValueError("Price expires before it was observed")
        if (self.service_start_date is None) != (self.service_end_date is None):
            raise ValueError("Provide both service dates or neither")
        if self.service_start_date and self.service_start_date > self.service_end_date:
            raise ValueError("Invalid price service-date range")
        return self


class TripExpense(Model):
    id: ShortText
    label: ShortText
    category: Category
    frequency: Literal["once", "per_day", "per_night"] = "once"
    units_per_occurrence: int = Field(default=1, strict=True, ge=1, le=100)
    dates: list[date] | None = Field(default=None, min_length=1, max_length=31)
    required: bool = Field(default=True, strict=True)
    selected_option_id: ShortText
    # Alternatives must already be acceptable for this expense/itinerary.
    options: list[PriceOption] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_options(self):
        ids = [p.id for p in self.options]
        if len(ids) != len(set(ids)) or self.selected_option_id not in ids:
            raise ValueError("Options must be unique and selected option must exist")
        if self.dates is not None:
            if len(self.dates) != len(set(self.dates)):
                raise ValueError("Duplicate expense dates")
            if self.frequency == "once" and len(self.dates) != 1:
                raise ValueError("One-off expenses accept at most one date")
        return self


class TripBudgetRequest(Model):
    start_date: date
    end_date: date
    travelers: int = Field(strict=True, ge=1, le=50)
    persons_per_room: int = Field(default=2, strict=True, ge=1, le=10)
    rooms: int | None = Field(default=None, strict=True, ge=1, le=50)
    budget_vnd: Money = Field(gt=0)
    budget_scope: Literal["group", "per_person"] = "group"
    reserve_pct: Decimal = Field(default=Decimal("10"), ge=0, le=100, decimal_places=2)
    expenses: list[TripExpense] = Field(max_length=200)
    required_categories: list[Category] = Field(
        default_factory=lambda: ["accommodation", "meals", "transport", "visits"],
        max_length=5,
    )
    propose_reductions: bool = Field(default=True, strict=True)
    allow_drop_optional: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def trip_rules(self):
        if not 0 <= (self.end_date - self.start_date).days <= 30:
            raise ValueError("Trip must last between 1 and 31 calendar days")
        if self.rooms is not None and self.rooms * self.persons_per_room < self.travelers:
            raise ValueError("Supplied rooms cannot accommodate all travelers")
        if len({e.id for e in self.expenses}) != len(self.expenses):
            raise ValueError("Duplicate expense IDs")
        if len(set(self.required_categories)) != len(self.required_categories):
            raise ValueError("Duplicate required categories")
        for expense in self.expenses:
            if expense.category != "accommodation" and any(o.billing_unit == "room" for o in expense.options):
                raise ValueError("Room billing is only supported for accommodation")
            last = self.end_date - timedelta(days=1) if expense.frequency == "per_night" else self.end_date
            if expense.dates and any(d < self.start_date or d > last for d in expense.dates):
                raise ValueError("Expense dates must be within chargeable trip dates")
        return self


class ExpenseCalculation(Model):
    expense_id: str
    option_id: str
    category: Category
    label: str
    billing_unit: str
    billing_units: int
    occurrences: int
    units_per_occurrence: int
    quantity: int
    min_total_vnd: Decimal | None
    max_total_vnd: Decimal | None
    certainty: str
    source: str
    observed_at: datetime | None
    valid_until: datetime | None
    price_state: Literal[
        "usable", "unknown", "expired", "future_observation", "outside_service_dates", "not_applicable"
    ]


class CostReduction(Model):
    expense_id: str
    action: Literal["replace", "drop_optional"]
    previous_option_id: str
    proposed_option_id: str | None
    max_cost_before_vnd: Decimal
    max_cost_after_vnd: Decimal
    saving_before_reserve_vnd: Decimal


class BudgetProposal(Model):
    status: Literal["fits_supplied_costs", "incomplete", "still_over_budget"]
    changes: list[CostReduction]
    proposed_max_with_reserve_vnd: Decimal
    savings_with_reserve_vnd: Decimal
    remaining_known_vnd: Decimal
    missing_categories: list[str]
    applied: Literal[False] = False


class TripBudgetReport(Model):
    request_id: UUID
    evaluated_at: datetime
    currency: Literal["VND"] = "VND"
    days: int
    nights: int
    travelers: int
    rooms: int
    group_budget_vnd: Decimal
    reserve_pct: Decimal
    known_min_vnd: Decimal
    known_max_vnd: Decimal
    reserve_vnd: Decimal
    known_max_with_reserve_vnd: Decimal
    remaining_known_vnd: Decimal
    over_budget_vnd: Decimal
    per_person_max_with_reserve_vnd: Decimal
    # Complete only with respect to supplied expense lines and required categories.
    coverage_complete: bool
    status: Literal["within_estimate", "at_risk", "over_budget", "incomplete"]
    unknown_expense_ids: list[str]
    missing_categories: list[str]
    estimated_expense_ids: list[str]
    category_known_max_vnd: dict[str, Decimal]
    lines: list[ExpenseCalculation]
    proposal: BudgetProposal | None = None
    warnings: list[str]


def expense_dates(data, expense):
    if expense.dates is not None:
        return sorted(expense.dates)
    if expense.frequency == "once":
        return [data.start_date]
    count = (data.end_date - data.start_date).days + (expense.frequency == "per_day")
    return [data.start_date + timedelta(days=i) for i in range(count)]


def calculate_line(data, expense, option, now):
    dates = expense_dates(data, expense)
    rooms = data.rooms or math.ceil(data.travelers / data.persons_per_room)
    units = {"person": data.travelers, "room": rooms, "group": 1}[option.billing_unit]
    quantity = units * len(dates) * expense.units_per_occurrence
    state = "usable"
    if not quantity:
        state = "not_applicable"
    elif option.certainty == "unknown":
        state = "unknown"
    elif option.observed_at and option.observed_at > now:
        state = "future_observation"
    elif option.valid_until and option.valid_until <= now:
        state = "expired"
    elif option.service_start_date and any(
        not option.service_start_date <= d <= option.service_end_date for d in dates
    ):
        state = "outside_service_dates"
    low = high = None
    if state == "not_applicable":
        low = high = ZERO
    elif state == "usable":
        low = dong(option.min_unit_price_vnd * quantity)
        high = dong(option.max_unit_price_vnd * quantity)
    return ExpenseCalculation(
        expense_id=expense.id,
        option_id=option.id,
        category=expense.category,
        label=expense.label,
        billing_unit=option.billing_unit,
        billing_units=units,
        occurrences=len(dates),
        units_per_occurrence=expense.units_per_occurrence,
        quantity=quantity,
        min_total_vnd=low,
        max_total_vnd=high,
        certainty=option.certainty,
        source=option.source,
        observed_at=option.observed_at,
        valid_until=option.valid_until,
        price_state=state,
    )


def with_reserve(value, pct):
    return value + dong(value * pct / Decimal("100"))


def propose(data, lines, cap, complete, now):
    baseline = sum((line.max_total_vnd or ZERO for line in lines), ZERO)
    opportunities = []
    for expense, current in zip(data.expenses, lines, strict=True):
        if current.price_state != "usable":
            continue
        best = current
        for option in expense.options:
            candidate = calculate_line(data, expense, option, now)
            if candidate.price_state == "usable" and candidate.max_total_vnd < best.max_total_vnd:
                best = candidate
        action = "replace"
        amount, next_id = best.max_total_vnd, best.option_id
        if data.allow_drop_optional and not expense.required and current.max_total_vnd > ZERO:
            action, amount, next_id = "drop_optional", ZERO, None
        saving = current.max_total_vnd - amount
        if saving > ZERO:
            opportunities.append(
                CostReduction(
                    expense_id=expense.id,
                    action=action,
                    previous_option_id=current.option_id,
                    proposed_option_id=next_id,
                    max_cost_before_vnd=current.max_total_vnd,
                    max_cost_after_vnd=amount,
                    saving_before_reserve_vnd=saving,
                )
            )
    # Independent expenses: largest available savings first minimizes number of
    # changed lines needed to reach the cap. It does not rank travel experience.
    opportunities.sort(key=lambda change: (-change.saving_before_reserve_vnd, change.expense_id))
    revised, changes = baseline, []
    for change in opportunities:
        if with_reserve(revised, data.reserve_pct) <= cap:
            break
        changes.append(change)
        revised -= change.saving_before_reserve_vnd
    maximum = with_reserve(revised, data.reserve_pct)
    dropped = {c.expense_id for c in changes if c.action == "drop_optional"}
    required = set(data.required_categories)
    if data.end_date == data.start_date:
        required.discard("accommodation")
    remaining_categories = {
        line.category for line in lines if line.quantity and line.expense_id not in dropped
    }
    missing = sorted(required - remaining_categories)
    return BudgetProposal(
        status="still_over_budget"
        if maximum > cap
        else ("fits_supplied_costs" if complete and not missing else "incomplete"),
        changes=changes,
        proposed_max_with_reserve_vnd=maximum,
        savings_with_reserve_vnd=with_reserve(baseline, data.reserve_pct) - maximum,
        remaining_known_vnd=cap - maximum,
        missing_categories=missing,
    )


class TripBudgetSpecialist(BaseAgent[TripBudgetRequest, TripBudgetReport]):
    name, input_schema, output_schema = "trip_budget_specialist", TripBudgetRequest, TripBudgetReport

    def __init__(self, now=None):
        self.now = now or (lambda: datetime.now(UTC))

    async def execute(self, data, context):
        now = aware(self.now())
        if now is None:
            raise ValueError("Clock must return a timezone-aware datetime")
        cap = data.budget_vnd * (data.travelers if data.budget_scope == "per_person" else 1)
        nights = (data.end_date - data.start_date).days
        lines = [
            calculate_line(
                data,
                expense,
                next(option for option in expense.options if option.id == expense.selected_option_id),
                now,
            )
            for expense in data.expenses
        ]
        low = sum((line.min_total_vnd or ZERO for line in lines), ZERO)
        high = sum((line.max_total_vnd or ZERO for line in lines), ZERO)
        unknown = [line.expense_id for line in lines if line.max_total_vnd is None]
        required = set(data.required_categories)
        if nights == 0:
            required.discard("accommodation")
        present = {line.category for line in lines if line.quantity > 0}
        missing = sorted(required - present)
        complete = bool(present) and not unknown and not missing
        maximum = with_reserve(high, data.reserve_pct)
        reserve = maximum - high
        status = (
            "over_budget"
            if low > cap
            else "incomplete"
            if not complete
            else "at_risk"
            if maximum > cap
            else "within_estimate"
        )
        categories = {}
        for line in lines:
            if line.max_total_vnd is not None:
                categories[line.category] = categories.get(line.category, ZERO) + line.max_total_vnd
        return TripBudgetReport(
            request_id=context.request_id,
            evaluated_at=now,
            days=nights + 1,
            nights=nights,
            travelers=data.travelers,
            rooms=data.rooms or math.ceil(data.travelers / data.persons_per_room),
            group_budget_vnd=cap,
            reserve_pct=data.reserve_pct,
            known_min_vnd=low,
            known_max_vnd=high,
            reserve_vnd=reserve,
            known_max_with_reserve_vnd=maximum,
            remaining_known_vnd=cap - maximum,
            over_budget_vnd=max(ZERO, maximum - cap),
            per_person_max_with_reserve_vnd=dong(maximum / data.travelers),
            coverage_complete=complete,
            status=status,
            unknown_expense_ids=unknown,
            missing_categories=missing,
            estimated_expense_ids=[
                line.expense_id for line in lines if line.certainty == "estimated" and line.quantity
            ],
            category_known_max_vnd=categories,
            lines=lines,
            proposal=propose(data, lines, cap, complete, now)
            if data.propose_reductions and maximum > cap
            else None,
            warnings=[
                "Đơn giá đầu vào phải gồm các thuế/phí bắt buộc; không tự lấy giá hoặc suy ra giá từ snippet.",
                "Tổng đã biết và quỹ dự phòng không bao gồm khoản chưa có giá; không xem khoản thiếu là miễn phí.",
                "Đủ dữ liệu chỉ xét khoản đã cung cấp và nhóm bắt buộc, chưa xác nhận mọi chi phí chuyến đi.",
                "Các lựa chọn thay thế phải đã đáp ứng nhu cầu, số người và dịch vụ của cùng khoản chi.",
                "Đề xuất chưa được áp dụng; đổi địa điểm/thời gian cần Planner kiểm tra lại tuyến và lịch trình.",
            ],
        )


async def assess_trip_budget(request_json: str) -> dict:
    """ADK-callable tool. All prices, sources and acceptable options are supplied input."""
    data = TripBudgetRequest.model_validate_json(request_json)
    result = await TripBudgetSpecialist().run(data, Context())
    return result.model_dump(mode="json")
