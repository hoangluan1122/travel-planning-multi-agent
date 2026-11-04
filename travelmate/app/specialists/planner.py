from ..adk_adapter import AdkPlanner
from ..agents import AgentError, BaseAgent
from ..models import Draft, PlannerInput
from ..orchestrator import validate_draft


class PlannerSpecialist(BaseAgent[PlannerInput, Draft]):
    """Standalone planner. Caller supplies evidence; never invokes another agent.

    planner_cls selects the engine: AdkPlanner takes an ADK model, MafPlanner takes a
    MAF chat-client factory. model_factory must produce what the engine expects.
    """

    name, input_schema, output_schema = "planner_specialist", PlannerInput, Draft

    def __init__(self, model_factory, planner_cls=AdkPlanner):
        self.model_factory = model_factory
        self.planner_cls = planner_cls

    async def execute(self, data, context):
        if not data.places.places:
            raise AgentError("Planner requires candidate places")
        if len(data.places.places) > 50:
            raise AgentError("Planner accepts at most 50 places")
        if len({p.id for p in data.places.places}) != len(data.places.places):
            raise AgentError("Duplicate candidate IDs")
        if self.planner_cls is AdkPlanner:
            planner = AdkPlanner(self.model_factory())
        else:
            planner = self.planner_cls(self.model_factory)
        result = await planner.plan(data, context)
        validate_draft(data.trip, result, data.places, data.constraints)
        return result
