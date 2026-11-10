"""Recommendation agent: ranks places by how well they match the user's interests.

The same real place listed twice (two map entries) is kept once, so a plan cannot visit it twice.
"""

from app.core.base import BaseAgent
from app.core.models import PlaceResult, RecommendationInput
from app.tools.places.same_place import drop_near_duplicates


class RecommendationAgent(BaseAgent[RecommendationInput, PlaceResult]):
    name, input_schema, output_schema = "recommendation", RecommendationInput, PlaceResult

    async def execute(self, data, context):
        interests = [s.casefold() for s in data.preferences.interests if s.strip()]
        ranked = sorted(
            drop_near_duplicates(data.places.places),
            key=lambda p: -sum(term in f"{p.name} {p.address}".casefold() for term in interests),
        )
        return PlaceResult(places=ranked, warnings=data.places.warnings)
