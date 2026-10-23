from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from ..agents import BaseAgent
from ..models import Model, ShortText


class CostLine(Model):
    id: ShortText
    category: Literal["accommodation", "meals", "transport", "visits", "other"]
    unit_price_vnd: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    quantity: int = Field(ge=1, le=10000, strict=True)
    source: str = Field(min_length=1, max_length=300)
    certainty: Literal["quoted", "estimated", "unknown"] = "unknown"

    @model_validator(mode="after")
    def check_price(self):
        if not self.source.strip():
            raise ValueError("Cost source must not be blank")
        if (self.unit_price_vnd is None) != (self.certainty == "unknown"):
            raise ValueError("Unknown certainty must have no price; known prices require certainty")
        return self


class BudgetRequest(Model):
    budget_vnd: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    lines: list[CostLine] = Field(max_length=500)
    required_categories: list[Literal["accommodation", "meals", "transport", "visits", "other"]] = Field(
        default_factory=lambda: ["accommodation", "meals", "transport", "visits"]
    )

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate cost-line IDs")
        return self


class BudgetReport(Model):
    currency: Literal["VND"] = "VND"
    subtotal_vnd: Decimal
    remaining_known_vnd: Decimal
    unknown_line_ids: list[str]
    missing_categories: list[str]
    estimated_line_ids: list[str]
    status: Literal["incomplete", "over_budget", "within_estimate"]
    line_totals: dict[str, Decimal | None]
    warnings: list[str]
    category_subtotals: dict[str, Decimal] = Field(default_factory=dict)
    quoted_subtotal_vnd: Decimal = Decimal("0")
    estimated_subtotal_vnd: Decimal = Decimal("0")


class BudgetSpecialist(BaseAgent[BudgetRequest, BudgetReport]):
    name, input_schema, output_schema = "budget_specialist", BudgetRequest, BudgetReport

    async def execute(self, data, context):
        totals = {
            line.id: None if line.unit_price_vnd is None else line.unit_price_vnd * line.quantity
            for line in data.lines
        }
        subtotal = sum((value for value in totals.values() if value is not None), Decimal("0"))
        missing = sorted(set(data.required_categories) - {line.category for line in data.lines})
        unknown = [key for key, value in totals.items() if value is None]
        estimated = [line.id for line in data.lines if line.certainty == "estimated"]
        categories = {}
        quoted_total = estimated_total = Decimal("0")
        for line in data.lines:
            value = totals[line.id]
            if value is None:
                continue
            categories[line.category] = categories.get(line.category, Decimal("0")) + value
            if line.certainty == "quoted":
                quoted_total += value
            else:
                estimated_total += value
        status = (
            "over_budget"
            if subtotal > data.budget_vnd
            else ("incomplete" if missing or unknown or not data.lines else "within_estimate")
        )
        return BudgetReport(
            subtotal_vnd=subtotal,
            remaining_known_vnd=data.budget_vnd - subtotal,
            unknown_line_ids=unknown,
            missing_categories=missing,
            estimated_line_ids=estimated,
            status=status,
            line_totals=totals,
            category_subtotals=categories,
            quoted_subtotal_vnd=quoted_total,
            estimated_subtotal_vnd=estimated_total,
            warnings=["Chỉ tính các khoản đầu vào; không phải báo giá hoặc xác nhận đủ mọi chi phí."],
        )
