"""Place agent: real places for the trip from the configured place provider (a tool)."""

from app.core.base import BaseAgent
from app.core.models import PlaceResult, TripRequest


class PlaceAgent(BaseAgent[TripRequest, PlaceResult]):
    name, input_schema, output_schema = "place", TripRequest, PlaceResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return await self.provider.search(data)
