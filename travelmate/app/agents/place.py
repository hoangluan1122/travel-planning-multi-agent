"""Place agent: real places for the trip from the configured place provider (a tool)."""

# Agent địa điểm: chỉ gọi nguồn địa điểm (provider) để lấy địa điểm thật cho chuyến đi. Cái khó nằm ở
# provider (app/tools/places/open_data_provider.py).

from app.core.base import BaseAgent
from app.core.models import PlaceResult, TripRequest


# name = 'place': orchestrator gọi agent này bằng registry.get('place').
class PlaceAgent(BaseAgent[TripRequest, PlaceResult]):
    name, input_schema, output_schema = "place", TripRequest, PlaceResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return await self.provider.search(data)
