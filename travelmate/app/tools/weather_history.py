"""Typical weather for dates beyond the forecast: the same days in the last few years.

Open-Meteo forecasts only 16 days ahead, so a trip planned a month out had no weather at
all. Its free historical archive (ERA5 reanalysis) has every past day, so for those dates
the plan shows what the same calendar days were like in each of the last three years: how
many of them had rain, and the usual low/high. It is labelled as such, never as a forecast,
and the scheduler does not treat it as one.
"""

# Thời tiết cùng kỳ các năm trước, cho những ngày quá xa để có dự báo (Open-Meteo chỉ dự báo 16 ngày).
# Lấy từ kho dữ liệu lịch sử miễn phí của Open-Meteo: mỗi ngày của chuyến đi, xem cùng ngày đó trong 3 năm
# trước có mưa không và nhiệt độ thường gặp. Trang ghi rõ đây là tham khảo, không phải dự báo; phần xếp
# lịch không dùng nó như dự báo.

import asyncio
import logging
from datetime import date

import httpx

from app.core.models import TypicalWeather

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
YEARS = 3
# Một ngày có từ 1 mm mưa trở lên được tính là ngày mưa.
RAIN_MM = 1.0


def years_back(day, n):
    """The same calendar day n years earlier (29/2 becomes 28/2)."""
    try:
        return day.replace(year=day.year - n)
    except ValueError:
        return day.replace(year=day.year - n, day=28)


class WeatherHistory:
    """typical(lat, lon, dates) -> [TypicalWeather]; an empty list when the archive is unavailable."""

    def __init__(self, transport=None, years=YEARS, timeout=8):
        self.transport, self.years, self.timeout = transport, years, timeout

    async def one_year(self, client, latitude, longitude, dates, n):
        """{trip date: (rain mm, low °C, high °C)} for the same days n years earlier."""
        shifted = {years_back(d, n): d for d in dates}
        response = await client.get(ARCHIVE_URL, params={
            "latitude": latitude, "longitude": longitude, "timezone": "Asia/Ho_Chi_Minh",
            "start_date": min(shifted).isoformat(), "end_date": max(shifted).isoformat(),
            "daily": "precipitation_sum,temperature_2m_min,temperature_2m_max",
        })
        response.raise_for_status()
        daily = response.json()["daily"]
        out = {}
        for raw, rain, low, high in zip(daily["time"], daily["precipitation_sum"], daily["temperature_2m_min"],
                                        daily["temperature_2m_max"], strict=True):
            trip_day = shifted.get(date.fromisoformat(raw))
            if trip_day is not None and rain is not None:
                out[trip_day] = (float(rain), low, high)
        return out

    async def typical(self, latitude, longitude, dates):
        dates = sorted(set(dates))
        if not dates:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                # Mỗi năm một yêu cầu, chạy song song; năm nào lỗi thì bỏ qua năm đó.
                years = await asyncio.gather(
                    *(self.one_year(client, latitude, longitude, dates, n) for n in range(1, self.years + 1)),
                    return_exceptions=True,
                )
        except Exception as exc:  # reference data must never fail a plan
            logger.warning("weather_history outcome=failed error_type=%s", type(exc).__name__)
            return []
        found = [y for y in years if isinstance(y, dict)]
        result = []
        for day in dates:
            samples = [y[day] for y in found if day in y]
            if not samples:
                continue
            lows = [low for _, low, _ in samples if low is not None]
            highs = [high for _, _, high in samples if high is not None]
            result.append(TypicalWeather(
                date=day,
                years=len(samples),
                rainy_years=sum(rain >= RAIN_MM for rain, _, _ in samples),
                temp_min_c=round(sum(lows) / len(lows)) if lows else None,
                temp_max_c=round(sum(highs) / len(highs)) if highs else None,
            ))
        return result
