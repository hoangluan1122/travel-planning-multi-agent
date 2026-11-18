"""MET Norway as the backup weather source when Open-Meteo fails."""

from datetime import date, datetime, timedelta

import httpx
import pytest
from test_open_data_provider import FakeGeo

from app.core.base import AgentError
from app.core.models import TripRequest
from app.tools.places.open_data_provider import OpenDataProvider
from app.tools.weather_met import MetNorway, wmo_for


def met_series(day, symbols, rain=1.0):
    """MET timeseries for one Vietnam day: 6-hour blocks at 07:00, 13:00, 19:00 local (00, 06, 12 UTC)."""
    out = []
    for hour_utc, symbol in zip((0, 6, 12), symbols):
        t = datetime(day.year, day.month, day.day, hour_utc)
        out.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {"next_6_hours": {
            "summary": {"symbol_code": symbol}, "details": {"precipitation_amount": rain}}}})
    return out


def met_transport(series, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"properties": {"timeseries": series}})
    return httpx.MockTransport(handler)


def test_met_symbols_map_to_wmo_codes():
    assert wmo_for("clearsky_day") == 0 and wmo_for("partlycloudy_night") == 2
    assert wmo_for("rainshowers_day") == 81 and wmo_for("heavyrain") == 65
    assert wmo_for("rainandthunder") == 95 and wmo_for("lightrainshowersandthunder_day") == 95
    assert wmo_for("unknown_symbol") is None


@pytest.mark.asyncio
async def test_daily_takes_the_worst_daytime_symbol_and_names_the_app():
    day = date(2026, 12, 1)
    seen = []
    met = MetNorway(contact="https://travel.example", transport=met_transport(
        met_series(day, ["fair_day", "heavyrain", "clearsky_night"], rain=6.0), seen))
    out = await met.daily(16.054412345, 108.2022)
    assert out[day].weather_code == 65 and out[day].elevated  # heavy rain, 6 mm in 6 hours
    request = seen[0]
    assert request.headers["User-Agent"] == "TravelMate/1.0 https://travel.example"
    assert request.url.params["lat"] == "16.0544"  # at most 4 decimals, as MET asks
    await met.daily(16.054412345, 108.2022)
    assert len(seen) == 1  # cached


class DownSpecialist:
    async def run(self, data, context):
        raise AgentError("Weather service returned HTTP 429")


def trip(days_ahead=2):
    start = date.today() + timedelta(days=days_ahead)
    return TripRequest(destination="Đà Nẵng", start_date=start, end_date=start + timedelta(days=1), travelers=2,
                       budget_vnd="5000000")


@pytest.mark.asyncio
async def test_open_meteo_down_uses_met_norway_and_says_so():
    t = trip()
    series = met_series(t.start_date, ["rainshowers_day", "cloudy", "cloudy"]) + \
        met_series(t.end_date, ["clearsky_day", "fair_day", "fair_night"], rain=0.0)
    provider = OpenDataProvider(images=False, geo=FakeGeo(), weather=DownSpecialist(), history=False,
                                backup_weather=MetNorway(transport=met_transport(series)))
    result = await provider.forecast(t)
    assert [(d.date, d.weather_code) for d in result.days] == [(t.start_date, 81), (t.end_date, 1)]
    assert any("MET Norway" in w and "Open-Meteo không trả lời" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_both_weather_sources_down_is_a_failure():
    dead = MetNorway(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    provider = OpenDataProvider(images=False, geo=FakeGeo(), weather=DownSpecialist(), history=False,
                                backup_weather=dead)
    with pytest.raises(AgentError, match="Both weather sources failed"):
        await provider.forecast(trip())
