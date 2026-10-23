import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from ..agents import BaseAgent
from .coccoc import BrowserBlocked, CardUnavailable, open_coccoc
from .models import (
    BrowserEvidence,
    BrowserWeatherRequest,
    BrowserWeatherResult,
    DailyForecast,
    HourForecast,
)
from .parsing import TZ, day_dates, location_matches, normalize, number, parse_stamp, parse_values

logger = logging.getLogger(__name__)


class BrowserWeatherTool(BaseAgent[BrowserWeatherRequest, BrowserWeatherResult]):
    name = "browser_weather_tool"
    input_schema, output_schema = BrowserWeatherRequest, BrowserWeatherResult

    def __init__(self, adapter_factory=None, *, evidence_dir: Path | None = None, now=None, timeout=55):
        if not 0 < timeout <= 60:
            raise ValueError("Browser weather timeout must be between zero and 60 seconds")
        self.adapter_factory = adapter_factory or open_coccoc
        self.evidence_dir = evidence_dir
        self.now = now or (lambda: datetime.now(TZ))
        self.timeout = timeout

    async def execute(self, data, context):
        result = BrowserWeatherResult(
            status="source_error",
            request=data,
            retrieved_at=self.now(),
            missing_hours=data.requested_hours(),
            warnings=[
                "Dự báo đọc từ bảng Cốc Cốc; chưa xác định nhà cung cấp khí tượng gốc.",
                "Đối chiếu theo tên địa danh; chưa xác minh tọa độ hoặc vi khí hậu tại điểm tham quan.",
                "Mốc giờ là mẫu theo giờ, không phải cam kết thời tiết suốt khoảng hoạt động.",
                "Lượng mưa giữ nguyên giá trị trên trang; thời lượng tích lũy chưa được xác minh.",
            ],
        )
        if data.location.scope == "province" or normalize(data.location.name) == normalize(
            data.location.province
        ):
            result.status = "needs_location"
            result.warnings.append("Cần tên khu vực/địa điểm cụ thể trong tỉnh.")
            return result
        if data.date < self.now().date():
            result.status = "outside_forecast"
            result.warnings.append("Tool này không tra thời tiết lịch sử.")
            return result
        queries = list(
            dict.fromkeys(
                [
                    f"thời tiết {data.location.name}",
                    f"dự báo thời tiết {data.location.name} {data.location.province}",
                    f"thời tiết {data.location.name}, {data.location.province}, Việt Nam",
                ]
            )
        )[:3]
        try:
            async with asyncio.timeout(self.timeout):
                async with self.adapter_factory() as browser:
                    for query in queries:
                        result.queries.append(query)
                        try:
                            snapshot = await browser.search(query)
                        except CardUnavailable:
                            continue
                        result.evidence.append(self._evidence(snapshot))
                        if not location_matches(data.location, snapshot["location"]):
                            result.status = "location_mismatch"
                            continue
                        result.resolved_location = snapshot["location"]
                        result.location_match = "name_match"
                        await self._extract(browser, snapshot, data, result, context)
                        result.retrieved_at = self.now()
                        return result
        except BrowserBlocked:
            result.status = "blocked"
            result.warnings.append("Nguồn yêu cầu xác minh hoặc từ chối truy cập; không vượt CAPTCHA.")
        except TimeoutError:
            result.status = "timeout"
            result.warnings.append("Hết thời gian truy cập bảng dự báo.")
        except (ImportError, ModuleNotFoundError):
            result.status = "source_error"
            result.warnings.append("Cần cài extra browser và trình duyệt Playwright/Edge.")
        except Exception as exc:
            logger.warning("browser_weather request=%s error_type=%s", context.request_id, type(exc).__name__)
            result.status = "source_error"
            result.warnings.append("Không đọc được bảng hoặc cấu trúc trang đã thay đổi.")
        # Never expose half-built or mismatched values as a usable forecast after failure.
        result.hourly, result.daily = [], None
        result.missing_hours = data.requested_hours()
        result.retrieved_at = self.now()
        return result

    def _evidence(self, snapshot):
        return BrowserEvidence(
            page_url=snapshot["url"],
            displayed_location=snapshot["location"],
            displayed_datetime=snapshot["stamp"],
            retrieved_at=self.now(),
            card_text=snapshot["text"][:12000],
        )

    async def _extract(self, browser, initial, request, result, context):
        anchor, _ = parse_stamp(initial["stamp"])
        # Do not use a stale widget as current-day evidence. One-day tolerance permits midnight rollover.
        if not self.now().date() - timedelta(days=1) <= anchor.date() <= self.now().date():
            raise CardUnavailable("Card date is stale or in the future")
        dates = day_dates(anchor.date(), [d["label"] for d in initial["days"]])
        if request.date not in dates:
            result.status = "outside_forecast"
            return
        index = dates.index(request.date)
        selected = await browser.select_day(index)
        stamp, _ = parse_stamp(selected["stamp"])
        if stamp.date() != request.date or not location_matches(request.location, selected["location"]):
            raise CardUnavailable("Day selection did not match requested location/date")
        result.evidence.append(self._evidence(selected))
        daily = initial["days"][index]
        # Daily highs/lows are never substituted for hourly forecasts.
        result.daily = DailyForecast(
            date=request.date, maximum_c=number(daily["high"], "°"), minimum_c=number(daily["low"], "°")
        )
        for hour in request.requested_hours():
            try:
                snapshot = await browser.select_hour(hour)
                stamp, has_hour = parse_stamp(snapshot["stamp"])
                if (
                    not has_hour
                    or stamp.date() != request.date
                    or stamp.hour != hour
                    or stamp.minute != 0
                    or not location_matches(request.location, snapshot["location"])
                ):
                    continue
                values = parse_values(snapshot)
                if values.temperature_c is None and values.precipitation_probability_pct is None:
                    continue
            except (CardUnavailable, ValueError, ValidationError):
                continue
            result.evidence.append(self._evidence(snapshot))
            result.hourly.append(
                HourForecast(at=stamp, evidence_index=len(result.evidence) - 1, **values.model_dump())
            )
        found = {h.at.hour for h in result.hourly}
        result.missing_hours = [h for h in request.requested_hours() if h not in found]
        complete = (
            bool(result.hourly)
            and not result.missing_hours
            and all(
                h.temperature_c is not None
                and h.precipitation_probability_pct is not None
                and h.wind_kmh is not None
                for h in result.hourly
            )
        )
        result.status = "ok" if complete else "partial"
        if not complete:
            result.warnings.append("Chưa lấy đủ dữ liệu theo giờ; không dùng dữ liệu cả ngày thay thế.")
        if self.evidence_dir:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"weather-{context.request_id}.png"
            try:
                await browser.screenshot(path)
                # Screenshot documents the final browser state, not every preceding hour.
                result.evidence.append(self._evidence(await browser.snapshot()))
                result.evidence[-1].screenshot = str(path.resolve())
            except Exception:
                result.warnings.append("Không lưu được ảnh bằng chứng; vẫn giữ nội dung DOM đã đọc.")


async def get_weather_from_browser(request_json: str) -> dict:
    """ADK function tool: pass BrowserWeatherRequest JSON, never arbitrary URLs.

    Returns structured forecast/status; location mismatch and missing data must not
    be represented as sunshine or zero rain. No booking or other agent calls.
    """
    from ..models import Context

    try:
        request = BrowserWeatherRequest.model_validate_json(request_json)
    except ValidationError as exc:
        return {
            "status": "invalid_input",
            "errors": [{"field": e["loc"], "type": e["type"]} for e in exc.errors()],
        }
    return (await BrowserWeatherTool().run(request, Context(), timeout=60)).model_dump(mode="json")
