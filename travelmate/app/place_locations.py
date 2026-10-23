from typing import Literal

from pydantic import Field

from .agents import AgentError
from .models import Model, Place, ShortText


class LocationCandidate(Model):
    id: str = Field(pattern=r"^osm:node/[1-9][0-9]*$")
    name: ShortText
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    locality_type: str
    address: str = ""
    source_url: str
    country_code: str = "VN"


class LocationChoiceRequired(AgentError):
    def __init__(self, candidates, reason):
        super().__init__("A specific location must be selected")
        self.candidates = candidates
        self.reason = reason


class LocationQuery(Model):
    destination: ShortText = Field(min_length=2)


class LocationResult(Model):
    candidates: list[LocationCandidate]
    warnings: list[str]


class PlaceDiscoveryResult(Model):
    status: Literal["candidates", "no_results", "needs_location"]
    places: list[Place] = Field(default_factory=list)
    location_options: list[LocationCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
