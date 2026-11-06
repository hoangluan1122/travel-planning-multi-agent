"""Recommendation agent: ranks places by how well they match the user's interests."""

from app.core.base import BaseAgent
from app.core.models import PlaceResult, RecommendationInput


class RecommendationAgent(BaseAgent[RecommendationInput, PlaceResult]):
    name, input_schema, output_schema = "recommendation", RecommendationInput, PlaceResult

    async def execute(self, data, context):
        interests = [s.casefold() for s in data.preferences.interests if s.strip()]
        ranked = sorted(
            data.places.places,
            key=lambda p: -sum(term in f"{p.name} {p.address}".casefold() for term in interests),
        )
        return PlaceResult(places=ranked, warnings=data.places.warnings)
