from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import Field, model_validator

from ..agents import AgentError, BaseAgent
from ..models import Model
from ..provider_http import get_with_retry


class WeatherRequest(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "Asia/Ho_Chi_Minh"
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA timezone") from None
        if not 0 <= (self.end_date - self.start_date).days <= 13:
            raise ValueError("Weather interval must be 1 to 14 days")
        return self


class ForecastDay(Model):
    date: date
    weather_code: int | None
    precipitation_probability: int | None = Field(ge=0, le=100)
    outdoor_risk: Literal["unknown", "elevated", "not_flagged"]


class WeatherReport(Model):
    status: Literal["available", "partial", "outside_forecast"]
    latitude: float
    longitude: float
    timezone: str
    fetched_at: datetime
    source: str = "https://open-meteo.com/"
    days: list[ForecastDay]
    missing_dates: list[date]
    warnings: list[str]
    provider_attempts: int = Field(default=0, ge=0, le=3)


class WeatherSpecialist(BaseAgent[WeatherRequest, WeatherReport]):
    name, input_schema, output_schema = "weather_specialist", WeatherRequest, WeatherReport

    def __init__(self, transport=None, now=None):
        self.transport = transport
        self.now = now or (lambda: datetime.now(UTC))

    async def execute(self, data, context):
        now = self.now()
        today = now.astimezone(ZoneInfo(data.timezone)).date()
        requested = [
            data.start_date + timedelta(days=i) for i in range((data.end_date - data.start_date).days + 1)
        ]
        eligible = [d for d in requested if today <= d <= today + timedelta(days=15)]
        days = []
        attempts = 0
        if eligible:
            try:
                async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
                    response, attempts = await get_with_retry(
                        client,
                        "https://api.open-meteo.com/v1/forecast",
                        params={
                            "latitude": data.latitude,
                            "longitude": data.longitude,
                            "timezone": data.timezone,
                            "forecast_days": 16,
                            "daily": "weather_code,precipitation_probability_max",
                        },
                    )
                    response.raise_for_status()
                daily = response.json()["daily"]
                fields = [daily[k] for k in ("time", "weather_code", "precipitation_probability_max")]
                if any(not isinstance(values, list) or len(values) > 16 for values in fields):
                    raise ValueError("Invalid daily forecast arrays")
                seen = set()
                for raw_date, code, rain in zip(
                    daily["time"], daily["weather_code"], daily["precipitation_probability_max"], strict=True
                ):
                    day = date.fromisoformat(raw_date)
                    if day in seen:
                        raise ValueError("Duplicate forecast date")
                    seen.add(day)
                    if code is not None and type(code) is not int:
                        raise ValueError("Weather code must be an integer or null")
                    if rain is not None and (type(rain) is not int or not 0 <= rain <= 100):
                        raise ValueError("Rain probability must be an integer from zero to 100")
                    if day not in eligible:
                        continue
                    risk = (
                        "unknown"
                        if code
                        not in {
                            0,
                            1,
                            2,
                            3,
                            45,
                            48,
                            51,
                            53,
                            55,
                            56,
                            57,
                            61,
                            63,
                            65,
                            66,
                            67,
                            71,
                            73,
                            75,
                            77,
                            80,
                            81,
                            82,
                            85,
                            86,
                            95,
                            96,
                            99,
                        }
                        or rain is None
                        else (
                            "elevated"
                            if code in {65, 67, 75, 77, 82, 85, 86, 95, 96, 99} or rain >= 70
                            else "not_flagged"
                        )
                    )
                    days.append(
                        ForecastDay(
                            date=day, weather_code=code, precipitation_probability=rain, outdoor_risk=risk
                        )
                    )
            except httpx.TimeoutException:
                raise TimeoutError("Weather service timed out") from None
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise AgentError("Weather service unavailable or invalid response") from None
        days.sort(key=lambda d: d.date)
        missing = [day for day in requested if day not in {d.date for d in days}]
        partial = missing or any(d.outdoor_risk == "unknown" for d in days)
        return WeatherReport(
            status="outside_forecast" if not eligible else "partial" if partial else "available",
            latitude=data.latitude,
            longitude=data.longitude,
            timezone=data.timezone,
            fetched_at=now,
            days=days,
            provider_attempts=attempts,
            missing_dates=missing,
            warnings=[
                "Nguồn Open-Meteo. Dự báo có thể thay đổi; không phải cảnh báo thời tiết chính thức.",
                "Ngưỡng rủi ro là quy tắc ứng dụng; not_flagged không có nghĩa là an toàn.",
            ],
        )
