import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.browser_weather.coccoc import BrowserBlocked, CardUnavailable
from app.browser_weather.models import BrowserWeatherRequest, BrowserWeatherResult, WeatherLocation
from app.browser_weather.parsing import TZ, day_dates, location_matches, parse_stamp, parse_values
from app.browser_weather.tool import BrowserWeatherTool, get_weather_from_browser
from app.models import Context

NOW = datetime(2026, 10, 22, 0, 15, tzinfo=TZ)


def request(**kwargs):
    return BrowserWeatherRequest.model_validate(
        {
            "location": {"name": "Sa Pa", "province": "Lào Cai"},
            "date": "2026-10-23",
            "start_time": "08:00",
            "end_time": "11:00",
            **kwargs,
        }
    )


def snapshot(location="Phường Sa Pa, Lào Cai", stamp="Thứ năm, 22/10/202600:00"):
    return {
        "location": location,
        "stamp": stamp,
        "url": "https://coccoc.com/search?query=weather",
        "temperature": "19°C",
        "feels_like": "19°C",
        "description": "Ít mây",
        "metrics": {"Độ ẩm": "72%", "Gió": "2 km/h", "Lượng mưa": "0mm", "Khả năng mưa": "0%"},
        "days": [
            {"label": "22 TH5", "high": "22°", "low": "13°"},
            {"label": "23 TH6", "high": "21°", "low": "14°"},
        ],
        "text": "Phường Sa Pa, Lào Cai · 23/10/2026 · 19°C · Gió 2 km/h · Khả năng mưa 0%",
    }


class Adapter:
    def __init__(self, labels=None, missing=False, invalid=False, blocked=False):
        self.labels = labels or ["Phường Sa Pa, Lào Cai"]
        self.missing, self.invalid, self.blocked = missing, invalid, blocked
        self.searches = 0
        self.closed = False

    async def search(self, query):
        if self.blocked:
            raise BrowserBlocked()
        label = self.labels[min(self.searches, len(self.labels) - 1)]
        self.searches += 1
        return snapshot(label)

    async def select_day(self, index):
        return snapshot(stamp="Thứ sáu, 23/10/2026")

    async def select_hour(self, hour):
        if self.missing and hour == 9:
            raise CardUnavailable()
        result = snapshot(stamp=f"Thứ sáu, 23/10/2026{hour:02}:00")
        if self.invalid:
            result["stamp"] = "Thứ năm, 22/10/202623:00"
        return result

    @asynccontextmanager
    async def session(self):
        try:
            yield self
        finally:
            self.closed = True


async def lookup(adapter, data=None):
    return await BrowserWeatherTool(adapter.session, now=lambda: NOW).run(data or request(), Context())


@pytest.mark.asyncio
async def test_reads_actual_hour_fields_not_daily_or_aqi():
    result = await lookup(Adapter())
    assert result.status == "ok"
    assert [h.at.hour for h in result.hourly] == [8, 9, 10]
    assert result.hourly[0].temperature_c == 19
    assert result.daily.maximum_c == 21
    assert result.hourly[0].precipitation_probability_pct == 0
    assert result.coordinate_match == "not_verified" and result.data_provider is None
    assert all(result.evidence[h.evidence_index].page_url for h in result.hourly)


@pytest.mark.asyncio
async def test_wrong_city_is_requeried_and_never_used():
    adapter = Adapter(labels=["Phường Lào Cai, Lào Cai", "Phường Sa Pa, Lào Cai"])
    result = await lookup(adapter)
    assert result.status == "ok" and adapter.searches == 2
    assert result.evidence[0].displayed_location == "Phường Lào Cai, Lào Cai"
    assert all(
        result.evidence[h.evidence_index].displayed_location == "Phường Sa Pa, Lào Cai" for h in result.hourly
    )


@pytest.mark.asyncio
async def test_all_mismatches_stop_after_three_queries():
    adapter = Adapter(labels=["Phường Lào Cai, Lào Cai"])
    result = await lookup(adapter)
    assert result.status == "location_mismatch" and adapter.searches == 3
    assert result.hourly == [] and result.daily is None


@pytest.mark.asyncio
async def test_missing_hour_is_partial_not_interpolated():
    result = await lookup(Adapter(missing=True))
    assert result.status == "partial" and result.missing_hours == [9]
    assert [h.at.hour for h in result.hourly] == [8, 10]


@pytest.mark.asyncio
async def test_current_conditions_not_used_as_future_forecast():
    result = await lookup(Adapter(invalid=True))
    assert result.status == "partial" and result.hourly == []


@pytest.mark.asyncio
async def test_blocked_stops_without_bypass():
    adapter = Adapter(blocked=True)
    result = await lookup(adapter)
    assert result.status == "blocked" and adapter.closed and len(result.queries) == 1


@pytest.mark.asyncio
async def test_province_scope_requires_locality_without_opening_browser():
    adapter = Adapter()
    result = await lookup(
        adapter, request(location={"name": "Lào Cai", "province": "Lào Cai", "scope": "province"})
    )
    assert result.status == "needs_location" and adapter.searches == 0


@pytest.mark.asyncio
async def test_requested_date_outside_widget():
    result = await lookup(Adapter(), request(date="2026-12-01"))
    assert result.status == "outside_forecast" and result.hourly == []


@pytest.mark.asyncio
async def test_timeout_closes_browser_and_returns_no_forecast():
    class Slow(Adapter):
        async def search(self, query):
            await asyncio.sleep(10)

    adapter = Slow()
    result = await BrowserWeatherTool(adapter.session, now=lambda: NOW, timeout=0.01).run(
        request(), Context()
    )
    assert result.status == "timeout" and adapter.closed and result.hourly == []


@pytest.mark.parametrize(
    "label,match",
    [
        ("Phường Sa Pa, Lào Cai", True),
        ("Thị xã Sapa, Lào Cai", True),
        ("Phường Lào Cai, Lào Cai", False),
        ("Sa Pa, tỉnh khác", False),
        ("Sa Pa", False),
        ("Sa Pa mở rộng, Lào Cai", False),
    ],
)
def test_exact_locality_and_province(label, match):
    assert location_matches(WeatherLocation(name="Sa Pa", province="Lào Cai"), label) is match


def test_month_and_year_rollover():
    anchor = datetime(2026, 12, 31).date()
    assert day_dates(anchor, ["31 TH5", "01 TH6"]) == [anchor, anchor + timedelta(days=1)]
    with pytest.raises(ValueError):
        day_dates(anchor, ["31 TH5", "01 TH7"])


def test_daily_and_hourly_stamps_are_distinct():
    assert parse_stamp("Thứ sáu, 23/10/2026")[1] is False
    assert parse_stamp("Thứ sáu, 23/10/202609:00")[0].hour == 9


def test_unknown_units_not_guessed():
    data = snapshot()
    data["metrics"]["Gió"] = "3 m/s"
    data["temperature"] = "80°F"
    values = parse_values(data)
    assert values.temperature_c is None and values.wind_kmh is None


@pytest.mark.asyncio
async def test_output_rejects_false_complete_claim():
    result = await lookup(Adapter(missing=True))
    raw = deepcopy(result.model_dump())
    raw["status"] = "ok"
    with pytest.raises(ValidationError):
        BrowserWeatherResult.model_validate(raw)


@pytest.mark.asyncio
async def test_llm_tool_invalid_input_does_not_open_browser():
    result = await get_weather_from_browser('{"url":"http://localhost/private"}')
    assert result["status"] == "invalid_input"


@pytest.mark.asyncio
async def test_ambiguous_province_name_requires_specific_label():
    adapter = Adapter()
    result = await lookup(adapter, request(location={"name": "Lào Cai", "province": "Lào Cai"}))
    assert result.status == "needs_location" and adapter.searches == 0


@pytest.mark.asyncio
async def test_evidence_cannot_be_reassigned_to_wrong_hour():
    result = await lookup(Adapter())
    raw = result.model_dump()
    raw["hourly"][0]["evidence_index"] = raw["hourly"][1]["evidence_index"]
    with pytest.raises(ValidationError, match="Evidence must match"):
        BrowserWeatherResult.model_validate(raw)


@pytest.mark.asyncio
async def test_stale_widget_not_treated_as_fresh_forecast():
    class Stale(Adapter):
        async def search(self, query):
            return snapshot(stamp="Thứ hai, 19/10/2026")

    result = await lookup(Stale())
    assert result.status == "source_error" and result.daily is None and not result.hourly


def test_browser_weather_api_auth_and_schema(tmp_path):
    from fastapi.testclient import TestClient

    from app.specialist_api import SpecialistSettings, create_app

    tool = BrowserWeatherTool(Adapter().session, now=lambda: NOW)
    app = create_app(
        SpecialistSettings(_env_file=None, travelmate_api_token="local-test"), {"weather_browser": tool}
    )
    with TestClient(app) as client:
        path = "/api/v1/tools/weather/browser"
        payload = request().model_dump(mode="json")
        assert client.post(path, json=payload).status_code == 401
        response = client.post(path, json=payload, headers={"Authorization": "Bearer local-test"})
        assert response.status_code == 200 and response.json()["status"] == "ok"
        assert response.headers["X-Request-ID"]
