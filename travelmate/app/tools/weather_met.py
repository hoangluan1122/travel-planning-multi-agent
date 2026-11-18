"""Backup weather forecast from MET Norway, for when Open-Meteo does not answer.

Open-Meteo's free API limits requests per IP address, and a free cloud server shares its
address with many other sites, so the site can be refused while the same request works
from home. MET Norway (api.met.no, the Norwegian Meteorological Institute) is free, needs
no key and covers Vietnam, about 10 days ahead. Its terms ask every request to name the
application and a way to reach it in the User-Agent, to cache answers, and to send no more
than 4 decimals of coordinates.

For Vietnam it gives a weather symbol and rain amount per hour / 6 hours, but no rain
probability, so a day's weather is its worst daytime symbol (mapped to a WMO code like
Open-Meteo's) and rain risk comes from heavy rain, thunder or 5 mm in 6 hours.
"""

# Nguồn thời tiết dự phòng MET Norway (Viện Khí tượng Na Uy), dùng khi Open-Meteo không trả lời.
# Open-Meteo miễn phí giới hạn lượt gọi theo địa chỉ IP, mà máy chủ miễn phí dùng chung IP với nhiều
# trang khác nên có thể bị từ chối. MET Norway miễn phí, không cần khoá, dự báo khoảng 10 ngày tới.
# Điều kiện của họ: ghi tên ứng dụng và cách liên hệ trong User-Agent, lưu đệm kết quả, toạ độ tối đa 4
# chữ số thập phân.

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
VIETNAM_UTC_OFFSET = timedelta(hours=7)
CACHE_S = 1800
# MET symbol (without _day/_night) -> WMO weather code, so the rest of the app reads it like Open-Meteo.
SYMBOL_WMO = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightsleet": 66, "sleet": 66, "heavysleet": 67,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleetshowers": 85, "sleetshowers": 85, "heavysleetshowers": 86,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}
HEAVY_WMO = {65, 67, 75, 82, 86, 95}
RAINY_MM_6H = 5.0


def wmo_for(symbol):
    """WMO code of a MET symbol such as 'rainshowers_day'; any thunder symbol is 95. None if unknown."""
    base = (symbol or "").split("_")[0]
    if "thunder" in base:
        return 95
    return SYMBOL_WMO.get(base)


class MetDay:
    """One day of MET forecast: WMO code, the most rain in 6 hours (mm), and whether to warn."""

    def __init__(self, day, weather_code, rain_mm):
        self.date, self.weather_code, self.rain_mm = day, weather_code, rain_mm
        self.elevated = weather_code in HEAVY_WMO or (rain_mm or 0) >= RAINY_MM_6H


class MetNorway:
    """daily(lat, lon) -> {date: MetDay} for Vietnam's local days; raises httpx errors on failure."""

    def __init__(self, contact="", transport=None, timeout=10):
        # "TravelMate/1.0 https://<site>": the application and how to reach it, as MET asks.
        self.user_agent = f"TravelMate/1.0 {contact}".strip() if contact else "TravelMate/1.0 (travel planner)"
        self.transport, self.timeout = transport, timeout
        self.cache = {}

    async def daily(self, latitude, longitude):
        key = (round(latitude, 4), round(longitude, 4))
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                     headers={"User-Agent": self.user_agent}) as client:
            response = await client.get(MET_URL, params={"lat": f"{key[0]:.4f}", "lon": f"{key[1]:.4f}"})
            response.raise_for_status()
            series = response.json()["properties"]["timeseries"]
        days = {}
        for entry in series:
            local = datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(UTC) + VIETNAM_UTC_OFFSET
            if not 6 <= local.hour < 19:  # the day's weather is the daytime weather
                continue
            block = entry["data"].get("next_6_hours") or entry["data"].get("next_1_hours") or {}
            code = wmo_for(block.get("summary", {}).get("symbol_code"))
            if code is None:
                continue
            rain = block.get("details", {}).get("precipitation_amount")
            day = days.setdefault(local.date(), {"codes": [], "rain": [], "hours": set()})
            day["codes"].append(code)
            day["hours"].add(local.hour)
            if rain is not None:
                day["rain"].append(float(rain))
        result = {}
        for day, d in days.items():
            if not any(h >= 12 for h in d["hours"]):  # a day cut off before noon is not a day's forecast
                continue
            result[day] = MetDay(day, max(d["codes"]), max(d["rain"]) if d["rain"] else None)
        self.cache[key] = (time.monotonic() + CACHE_S, result)
        return result
