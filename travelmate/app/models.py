from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TripRequest(Model):
    destination: str = Field(min_length=2, max_length=200)
    start_date: date
    end_date: date
    travelers: int = Field(ge=1, le=50)
    budget_vnd: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    interests: list[ShortText] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=1500)

    @model_validator(mode="after")
    def validate_dates(self):
        if not self.destination.strip():
            raise ValueError("Destination must not be blank")
        if self.start_date < date.today():
            raise ValueError("Start date must not be in the past")
        if not 0 <= (self.end_date - self.start_date).days <= 13:
            raise ValueError("Trip must last 1 to 14 days")
        return self


class Context(Model):
    request_id: UUID = Field(default_factory=uuid4)


class PlaceSearchRequest(Model):
    destination: str = Field(min_length=2, max_length=200)
    category: Literal["attraction", "hotel", "restaurant"] = "attraction"
    limit: int = Field(default=12, ge=1, le=20)
    keyword: str = Field(default="", max_length=120)
    location_id: str | None = Field(default=None, pattern=r"^osm:node/[1-9][0-9]*$", max_length=100)
    radius_m: int = Field(default=3000, ge=100, le=10000)

    @model_validator(mode="after")
    def normalize_destination(self):
        self.destination = self.destination.strip()
        if len(self.destination) < 2:
            raise ValueError("Destination must contain at least two characters")
        return self


class Preferences(Model):
    interests: list[str]
    source: Literal["current_request_only", "request_and_saved_memory"] = "current_request_only"
    warnings: list[str] = Field(default_factory=list)


class PlacePhoto(Model):
    """A displayable image: an https URL or a same-origin proxy path, with its credit."""

    url: str = Field(min_length=1, max_length=2000)
    attribution: str = Field(max_length=500)
    source_url: str | None = Field(default=None, max_length=2000)


class PriceRange(Model):
    """Per-person price range reported by the source (e.g. Google Places priceRange)."""

    low_vnd: Decimal | None = Field(default=None, ge=0)
    high_vnd: Decimal | None = Field(default=None, ge=0)


class TicketInfo(Model):
    """Entrance fee from the curated, cited table in app/data/ticket_prices.json."""

    group_id: ShortText  # one ticket can cover several places (e.g. the whole Imperial City)
    label: str = Field(max_length=300)
    adult_vnd: Decimal | None = Field(default=None, ge=0)
    low_vnd: Decimal | None = Field(default=None, ge=0)
    high_vnd: Decimal | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=300)
    sources: list[str] = Field(default_factory=list, max_length=5)
    checked: date


class Place(Model):
    id: ShortText
    name: ShortText
    address: str = Field(max_length=2000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: ShortText
    types: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None
    estimated_visit_cost_vnd: Decimal | None = Field(default=None, ge=0)
    source_url: str | None = None
    attribution: str | None = None
    coordinate_kind: Literal["point", "geometry_center", "unspecified"] = "unspecified"
    opening_hours_raw: str | None = Field(default=None, max_length=2000)
    website_url: str | None = Field(default=None, max_length=2000)
    image_reference: str | None = Field(default=None, max_length=2000)
    field_sources: dict[str, str] = Field(default_factory=dict)
    photo: PlacePhoto | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0)
    price_level: Literal["free", "inexpensive", "moderate", "expensive", "very_expensive"] | None = None
    price_range: PriceRange | None = None
    maps_url: str | None = Field(default=None, max_length=2000)
    ticket: TicketInfo | None = None


class PlaceResult(Model):
    places: list[Place]
    warnings: list[str] = Field(default_factory=list)
    # Accommodation candidates; shown with the plan, never scheduled as activities.
    stays: list[Place] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_places(self):
        if len({p.id for p in self.places}) != len(self.places):
            raise ValueError("Place IDs must be unique")
        return self


class WeatherDay(Model):
    date: date
    weather_code: int


class WeatherResult(Model):
    days: list[WeatherDay] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecommendationInput(Model):
    places: PlaceResult
    preferences: Preferences


class Activity(Model):
    place_id: str
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @model_validator(mode="after")
    def positive_duration(self):
        if self.end_minute <= self.start_minute:
            raise ValueError("Activity must have positive duration")
        return self


class Day(Model):
    date: date
    activities: list[Activity] = Field(min_length=1, max_length=8)


class Draft(Model):
    days: list[Day] = Field(min_length=1, max_length=14)


class PlannerInput(Model):
    trip: TripRequest
    places: PlaceResult
    weather: WeatherResult
    constraints: "ScheduleConstraints" = Field(default_factory=lambda: ScheduleConstraints())
    # Merged request + saved interests. Reaches the LLM only as inspect_trip data, never
    # as prompt instructions, so saved text cannot act as a command.
    preferences: Preferences | None = None

    @model_validator(mode="after")
    def consistent_evidence(self):
        ids = {p.id for p in self.places.places}
        if not set(self.constraints.required_place_ids) <= ids:
            raise ValueError("Required places must be supplied as candidates")
        if not set(self.constraints.excluded_place_ids) <= ids:
            raise ValueError("Excluded places must be supplied as candidates")
        if not set(self.constraints.visit_windows) <= ids:
            raise ValueError("Visit windows must refer to supplied candidates")
        dates = [d.date for d in self.weather.days]
        if len(set(dates)) != len(dates) or any(
            not self.trip.start_date <= d <= self.trip.end_date for d in dates
        ):
            raise ValueError("Weather dates must be unique and within the trip")
        return self


class ScheduleWindow(Model):
    opens_minute: int = Field(ge=0, le=1439)
    closes_minute: int = Field(ge=1, le=1440)
    source: ShortText

    @model_validator(mode="after")
    def ordered(self):
        if self.opens_minute >= self.closes_minute:
            raise ValueError("Visit window must have positive duration")
        return self


class ScheduleConstraints(Model):
    day_start_minute: int = Field(default=0, ge=0, le=1439)
    day_end_minute: int = Field(default=1440, ge=1, le=1440)
    min_activity_minutes: int = Field(default=1, ge=1, le=1440)
    max_activities_per_day: int = Field(default=8, ge=1, le=8)
    required_place_ids: list[ShortText] = Field(default_factory=list, max_length=50)
    excluded_place_ids: list[ShortText] = Field(default_factory=list, max_length=50)
    visit_windows: dict[str, ScheduleWindow] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def consistent(self):
        if self.day_end_minute - self.day_start_minute < self.min_activity_minutes:
            raise ValueError("Daily window is shorter than minimum activity duration")
        if set(self.required_place_ids) & set(self.excluded_place_ids):
            raise ValueError("A place cannot be both required and excluded")
        for ids in (self.required_place_ids, self.excluded_place_ids):
            if len(set(ids)) != len(ids):
                raise ValueError("Constraint IDs must be unique")
        return self


PlannerInput.model_rebuild()


class BudgetInput(Model):
    trip: TripRequest
    draft: Draft
    places: PlaceResult


class BudgetResult(Model):
    currency: Literal["VND"] = "VND"
    known_subtotal: Decimal
    unknown_items: list[str]
    status: Literal["incomplete", "over_budget", "within_budget"]
    # Range from source price ranges (e.g. restaurants' priceRange x travelers), not a quote.
    estimated_low_vnd: Decimal | None = Field(default=None, ge=0)
    estimated_high_vnd: Decimal | None = Field(default=None, ge=0)
    estimate_basis: list[str] = Field(default_factory=list)


AgentName = Literal["places", "place_search", "weather", "recommendation", "itinerary", "budget"]
CORE = ("places", "weather", "recommendation", "itinerary", "budget")
# Dependencies every plan must state, so the plan describes what will really happen.
REQUIRED_EDGES = {"recommendation": {"places", "place_search"}, "itinerary": {"recommendation", "weather"},
                  "budget": {"itinerary"}}
MAX_TARGETED_SEARCHES = 4
MAX_REPLANS = 2


class SubTaskInputs(Model):
    category: Literal["attraction", "restaurant", "hotel"] | None = None
    keyword: str = Field(default="", max_length=60)


class TravelSubTask(Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,30}$")
    agent: AgentName
    goal: str = Field(min_length=3, max_length=300)
    inputs: SubTaskInputs = Field(default_factory=SubTaskInputs)
    depends_on: list[str] = Field(default_factory=list, max_length=8)


class TravelPlan(Model):
    """Planning-pattern plan; validated as a submit gate (see app/planning.py)."""

    subtasks: list[TravelSubTask] = Field(min_length=len(CORE), max_length=len(CORE) + MAX_TARGETED_SEARCHES)

    @model_validator(mode="after")
    def executable(self):
        ids = [t.id for t in self.subtasks]
        if len(set(ids)) != len(ids):
            raise ValueError("Subtask ids must be unique")
        for task in self.subtasks:
            if task.agent != "place_search":
                task.inputs = SubTaskInputs()  # inputs only mean something for targeted searches
        counts = {name: sum(t.agent == name for t in self.subtasks) for name in CORE}
        if any(n != 1 for n in counts.values()):
            raise ValueError("Exactly one subtask each for places, weather, recommendation, itinerary, budget")
        by_id = {t.id: t for t in self.subtasks}
        for task in self.subtasks:
            unknown = set(task.depends_on) - set(by_id)
            if unknown or task.id in task.depends_on:
                raise ValueError(f"Subtask {task.id} depends on unknown or itself: {sorted(unknown)}")
            if task.agent == "place_search":
                if task.inputs.category is None or not task.inputs.keyword.strip():
                    raise ValueError(f"place_search {task.id} needs a category and a keyword")
                if task.depends_on:
                    raise ValueError("place_search runs first and depends on nothing")
            needed = REQUIRED_EDGES.get(task.agent, set())
            have = {by_id[d].agent for d in task.depends_on}
            for agent in needed:
                if agent == "place_search":
                    searches = {t.id for t in self.subtasks if t.agent == "place_search"}
                    if not searches <= set(task.depends_on):
                        raise ValueError(f"{task.id} must depend on every place_search subtask")
                elif agent not in have:
                    raise ValueError(f"{task.id} ({task.agent}) must depend on a {agent} subtask")
        # Acyclic: repeatedly remove subtasks whose dependencies are done.
        done, pending = set(), dict(by_id)
        while pending:
            ready = [i for i, t in pending.items() if set(t.depends_on) <= done]
            if not ready:
                raise ValueError("Subtask dependencies form a cycle")
            for i in ready:
                done.add(i)
                pending.pop(i)
        return self

    def of(self, agent):
        return [t for t in self.subtasks if t.agent == agent]


class Observation(Model):
    subtask_id: str
    outcome: Literal["ok", "no_results", "failed"]
    count: int = 0


class PlanRound(Model):
    round: int
    plan: TravelPlan
    observations: list[Observation] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=300)


class PlanningTrace(Model):
    planner: Literal["llm", "default"]
    rounds: list[PlanRound]



class PlanResponse(Model):
    request_id: UUID
    mode: Literal["demo", "live"]
    status: Literal["draft_unverified"] = "draft_unverified"
    draft: Draft
    places: list[Place]
    weather: WeatherResult
    budget: BudgetResult
    warnings: list[str]
    stays: list[Place] = Field(default_factory=list)
    planning: PlanningTrace | None = None
