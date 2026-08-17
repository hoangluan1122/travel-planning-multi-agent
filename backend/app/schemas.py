from datetime import date
from pydantic import BaseModel, Field, model_validator


class TripRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    budget: int = Field(gt=0, description="Tổng ngân sách theo VNĐ")
    interests: list[str] = Field(default_factory=list)
    traveler_id: str | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date phải sau hoặc bằng start_date")
        return self


class Activity(BaseModel):
    time: str
    title: str
    category: str
    estimated_cost: int
    note: str


class ItineraryDay(BaseModel):
    day: int
    date: date
    activities: list[Activity]


class TripPlan(BaseModel):
    destination: str
    total_budget: int
    estimated_cost: int
    weather_summary: str
    itinerary: list[ItineraryDay]
    recommendations: list[str]

