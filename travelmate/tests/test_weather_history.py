"""Past years' weather for trip days beyond the 16-day forecast."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from test_open_data_provider import FakeGeo

from app.agents.concierge import ChatService, ChatSession, HandOff, TripSlots
from app.core.models import Context, TripRequest, TypicalWeather, WeatherResult
from app.specialists.weather import WeatherReport
from app.tools.places.open_data_provider import OpenDataProvider
from app.tools.weather_history import WeatherHistory, years_back


def archive(by_year, fail_years=()):
    """MockTransport for the archive: by_year {year: (rain mm, low, high)} for every requested day."""
    seen = []

    def handler(request):
        seen.append(request)
        start = date.fromisoformat(request.url.params["start_date"])
        end = date.fromisoformat(request.url.params["end_date"])
        if start.year in fail_years:
            return httpx.Response(503)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        rain, low, high = by_year[start.year]
        return httpx.Response(200, json={"daily": {
            "time": [d.isoformat() for d in days], "precipitation_sum": [rain] * len(days),
            "temperature_2m_min": [low] * len(days), "temperature_2m_max": [high] * len(days),
        }})

    return httpx.MockTransport(handler), seen


def test_years_back_keeps_the_calendar_day_and_handles_29_february():
    assert years_back(date(2027, 1, 3), 1) == date(2026, 1, 3)
    assert years_back(date(2028, 2, 29), 1) == date(2027, 2, 28)


@pytest.mark.asyncio
async def test_typical_counts_rainy_years_and_averages_temperatures():
    transport, seen = archive({2025: (5.0, 20.0, 27.0), 2024: (0.2, 22.0, 29.0), 2023: (12.0, 21.0, 28.0)})
    days = [date(2026, 12, 8), date(2026, 12, 9)]
    out = await WeatherHistory(transport=transport).typical(15.88, 108.33, days)
    assert [t.date for t in out] == days
    assert out[0].years == 3 and out[0].rainy_years == 2  # 0.2 mm is not a rainy day
    assert (out[0].temp_min_c, out[0].temp_max_c) == (21, 28)
    assert len(seen) == 3  # one request per past year


@pytest.mark.asyncio
async def test_a_failed_year_is_skipped_and_a_dead_archive_gives_nothing():
    transport, _ = archive({2025: (5.0, 20.0, 27.0), 2023: (0.0, 21.0, 28.0)}, fail_years={2024})
    out = await WeatherHistory(transport=transport).typical(15.88, 108.33, [date(2026, 12, 8)])
    assert out[0].years == 2 and out[0].rainy_years == 1
    dead = httpx.MockTransport(lambda request: httpx.Response(503))
    assert await WeatherHistory(transport=dead).typical(15.88, 108.33, [date(2026, 12, 8)]) == []


class NoForecast:
    """The specialist's answer for days beyond the forecast window."""

    async def run(self, data, context):
        return WeatherReport(
            status="outside_forecast", latitude=data.latitude, longitude=data.longitude, timezone=data.timezone,
            fetched_at=datetime.now(UTC), days=[],
            missing_dates=[data.start_date + timedelta(days=i) for i in range((data.end_date - data.start_date).days + 1)],
            warnings=["Nguồn Open-Meteo.", "Ngưỡng rủi ro là quy tắc ứng dụng; not_flagged không có nghĩa là an toàn."],
        )


def far_trip(days_ahead=40, length=2):
    start = date.today() + timedelta(days=days_ahead)
    return TripRequest(destination="Hội An", start_date=start, end_date=start + timedelta(days=length),
                       travelers=2, budget_vnd="5000000")


@pytest.mark.asyncio
async def test_days_beyond_the_forecast_get_past_years_weather_and_say_why():
    transport, _ = archive({y: (3.0, 22.0, 27.0) for y in range(2020, 2030)})
    provider = OpenDataProvider(images=False, geo=FakeGeo(), weather=NoForecast(),
                                history=WeatherHistory(transport=transport))
    result = await provider.forecast(far_trip())
    assert not result.days  # never passed off as a forecast (the scheduler reads only days)
    assert len(result.typical) == 3 and result.typical[0].rainy_years == 3
    text = " ".join(result.warnings)
    assert "16 ngày tới" in text and "cùng kỳ các năm trước" in text and "không phải dự báo" in text
    assert "not_flagged" not in text


@pytest.mark.asyncio
async def test_without_history_the_note_still_explains_the_missing_forecast():
    provider = OpenDataProvider(images=False, geo=FakeGeo(), weather=NoForecast(), history=False)
    result = await provider.forecast(far_trip())
    assert not result.typical
    assert any("Chưa có dự báo" in w and "16 ngày tới" in w for w in result.warnings)


class TypicalOnly:
    async def forecast(self, trip):
        return WeatherResult(typical=[TypicalWeather(date=trip.start_date, years=3, rainy_years=2,
                                                     temp_min_c=7, temp_max_c=13)])


@pytest.mark.asyncio
async def test_chat_weather_answer_uses_past_years_and_says_it_is_not_a_forecast():
    chat = ChatService(orchestrator=None, provider=TypicalOnly())
    session = ChatSession()
    start = date.today() + timedelta(days=40)
    session.slots = TripSlots(destination="Sa Pa", start_date=start, end_date=start)
    reply = await chat.weather_advisor(session, HandOff(agent="weather_advisor", reason="hỏi thời tiết"), Context())
    assert "2/3 năm có mưa" in reply.text and "7–13°C" in reply.text and "không phải dự báo" in reply.text
