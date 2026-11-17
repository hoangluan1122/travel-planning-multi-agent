"""Browser-backed weather extraction. No LLM-generated forecast values."""

# Đọc thời tiết từ trình duyệt (ô thời tiết của Cốc Cốc). Số liệu chỉ lấy từ trang, không do LLM tạo. Ứng
# dụng phụ, chạy riêng; trang web chính không dùng file này.

from app.tools.browser_weather.models import BrowserWeatherRequest, BrowserWeatherResult
from app.tools.browser_weather.tool import BrowserWeatherTool

__all__ = ["BrowserWeatherRequest", "BrowserWeatherResult", "BrowserWeatherTool"]
