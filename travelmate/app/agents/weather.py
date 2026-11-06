"""Weather agent: the forecast for the trip's dates from the weather provider (a tool)."""

from app.core.base import BaseAgent
from app.core.models import TripRequest, WeatherResult


class WeatherAgent(BaseAgent[TripRequest, WeatherResult]):
    name, input_schema, output_schema = "weather", TripRequest, WeatherResult

    def __init__(self, provider):
        self.provider = provider

    async def execute(self, data, context):
        return await self.provider.forecast(data)
