"""Itinerary agent: places into a day-by-day schedule (LLM when configured, else a demo schedule)."""

from datetime import timedelta

from app.core.base import AgentError, BaseAgent
from app.core.models import Activity, Day, Draft, PlannerInput


class PlannerAgent(BaseAgent[PlannerInput, Draft]):
    name, input_schema, output_schema = "planner", PlannerInput, Draft

    def __init__(self, llm=None):
        self.llm = llm

    async def execute(self, data, context):
        if not data.places.places:
            raise AgentError("No places found; change destination or criteria")
        if self.llm is not None:
            return await self.llm.plan(data, context)
        # Explicitly demo-only schedule, not a real route optimization.
        return Draft(
            days=[
                Day(
                    date=data.trip.start_date + timedelta(days=i),
                    activities=[
                        Activity(
                            place_id=data.places.places[i % len(data.places.places)].id,
                            start_minute=540,
                            end_minute=660,
                        )
                    ],
                )
                for i in range((data.trip.end_date - data.trip.start_date).days + 1)
            ]
        )
