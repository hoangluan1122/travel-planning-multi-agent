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
    source: str = "current_request_only"


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


class PlaceResult(Model):
    places: list[Place]
    warnings: list[str] = Field(default_factory=list)

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


class PlanResponse(Model):
    request_id: UUID
    mode: Literal["demo", "live"]
    status: Literal["draft_unverified"] = "draft_unverified"
    draft: Draft
    places: list[Place]
    weather: WeatherResult
    budget: BudgetResult
    warnings: list[str]
