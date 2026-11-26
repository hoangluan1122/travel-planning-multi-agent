"""Planner specialist (standalone test bench): schedules days from evidence the caller supplies."""

# Chuyên gia xếp lịch chạy riêng: người gọi đưa sẵn địa điểm và thời tiết. Thuộc 'bàn thử chuyên gia'
# (app/specialists): mỗi chuyên gia chạy riêng lẻ để thử và chấm điểm, không gọi agent khác. Trang web chính
# không dùng file này trừ khi ghi rõ.

from app.agents.orchestrator import validate_draft
from app.core.base import AgentError, BaseAgent
from app.core.llm.maf_adapter import MafPlanner
from app.core.models import Draft, PlannerInput


class PlannerSpecialist(BaseAgent[PlannerInput, Draft]):
    """Standalone planner. Caller supplies evidence; never invokes another agent.

    model_factory returns a fresh MAF chat client per call; planner_cls is MafPlanner or a
    test double with the same constructor.
    """

    name, input_schema, output_schema = "planner_specialist", PlannerInput, Draft

    def __init__(self, model_factory, planner_cls=MafPlanner):
        self.model_factory = model_factory
        self.planner_cls = planner_cls

    async def execute(self, data, context):
        if not data.places.places:
            raise AgentError("Planner requires candidate places")
        if len(data.places.places) > 50:
            raise AgentError("Planner accepts at most 50 places")
        if len({p.id for p in data.places.places}) != len(data.places.places):
            raise AgentError("Duplicate candidate IDs")
        planner = self.planner_cls(self.model_factory)
        result = await planner.plan(data, context)
        validate_draft(data.trip, result, data.places, data.constraints)
        return result
