from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import Field, model_validator

from ..models import Model, ShortText


class WeatherLocation(Model):
    name: ShortText
    province: ShortText
    country_code: Literal["VN"] = "VN"
    scope: Literal["locality", "province", "point_of_interest"] = "locality"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both coordinates or neither")
        return self


class BrowserWeatherRequest(Model):
    location: WeatherLocation
    date: date
    start_time: time
    end_time: time
    timezone: Literal["Asia/Ho_Chi_Minh"] = "Asia/Ho_Chi_Minh"

    @model_validator(mode="after")
    def interval(self):
        if self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Use local times without offsets")
        if self.start_time >= self.end_time:
            raise ValueError("Use a same-day interval with start before end")
        if any(t.second or t.microsecond for t in [self.start_time, self.end_time]):
            raise ValueError("Time precision is minutes")
        return self

    def requested_hours(self):
        """Hourly samples covering [start,end); never interpolate provider values."""
        last = self.end_time.hour + bool(self.end_time.minute)
        return list(range(self.start_time.hour, last))


class WeatherValues(Model):
    description: str | None = Field(default=None, max_length=200)
    temperature_c: float | None = Field(default=None, ge=-100, le=70)
    feels_like_c: float | None = Field(default=None, ge=-120, le=90)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    wind_kmh: float | None = Field(default=None, ge=0, le=500)
    precipitation_mm: float | None = Field(default=None, ge=0, le=5000)
    precipitation_probability_pct: float | None = Field(default=None, ge=0, le=100)


class HourForecast(WeatherValues):
    at: datetime
    evidence_index: int = Field(ge=0)


class DailyForecast(Model):
    date: date
    minimum_c: float | None = Field(default=None, ge=-100, le=70)
    maximum_c: float | None = Field(default=None, ge=-100, le=70)

    @model_validator(mode="after")
    def order(self):
        if self.minimum_c is not None and self.maximum_c is not None and self.minimum_c > self.maximum_c:
            raise ValueError("Daily min exceeds max")
        return self


class BrowserEvidence(Model):
    page_url: str
    displayed_location: str
    displayed_datetime: str
    retrieved_at: datetime
    card_text: str = Field(max_length=12000)
    screenshot: str | None = None


class BrowserWeatherResult(Model):
    status: Literal[
        "ok",
        "partial",
        "needs_location",
        "location_mismatch",
        "outside_forecast",
        "blocked",
        "source_error",
        "timeout",
    ]
    request: BrowserWeatherRequest
    resolved_location: str | None = None
    location_match: Literal["unverified", "name_match"] = "unverified"
    coordinate_match: Literal["not_verified"] = "not_verified"
    hourly: list[HourForecast] = Field(default_factory=list)
    daily: DailyForecast | None = None
    missing_hours: list[int] = Field(default_factory=list)
    source: Literal["Cốc Cốc weather card"] = "Cốc Cốc weather card"
    data_provider: str | None = None
    retrieved_at: datetime
    evidence: list[BrowserEvidence] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def grounded(self):
        from .parsing import location_matches, parse_stamp

        hours = set()
        for sample in self.hourly:
            if sample.at.utcoffset() != timedelta(hours=7) or sample.at.date() != self.request.date:
                raise ValueError("Sample must have a timezone and match requested date")
            if sample.at.hour not in self.request.requested_hours() or sample.at.hour in hours:
                raise ValueError("Unexpected or duplicate forecast hour")
            if sample.evidence_index >= len(self.evidence):
                raise ValueError("Forecast must refer to captured evidence")
            evidence = self.evidence[sample.evidence_index]
            stamp, has_hour = parse_stamp(evidence.displayed_datetime)
            if (
                not has_hour
                or stamp != sample.at
                or not location_matches(self.request.location, evidence.displayed_location)
            ):
                raise ValueError("Evidence must match the sample's timestamp and requested locality")
            hours.add(sample.at.hour)
        if self.missing_hours != [h for h in self.request.requested_hours() if h not in hours]:
            raise ValueError("Missing-hour list must match actual coverage")
        if self.daily and self.daily.date != self.request.date:
            raise ValueError("Daily forecast must match requested date")
        if self.status in {"ok", "partial"} and (self.location_match != "name_match" or not self.evidence):
            raise ValueError("Usable forecasts require verified label and evidence")
        if self.status == "ok":
            if set(self.request.requested_hours()) != hours or self.missing_hours:
                raise ValueError("Complete result must cover requested hourly samples")
            if any(
                h.temperature_c is None or h.precipitation_probability_pct is None or h.wind_kmh is None
                for h in self.hourly
            ):
                raise ValueError("Complete result requires temperature, rain probability and wind")
        if self.status not in {"ok", "partial"} and (self.hourly or self.daily):
            raise ValueError("Failed or mismatched lookup cannot contain usable forecasts")
        return self
