from dataclasses import dataclass


@dataclass
class Place:
    name: str
    category: str
    cost: int
    note: str


class PlaceAgent:
    """Nơi tích hợp Google Places API trong giai đoạn tiếp theo."""

    def find_places(self, destination: str, interests: list[str]) -> list[Place]:
        labels = interests or ["tham quan", "ẩm thực", "văn hóa"]
        return [
            Place(f"Điểm {label.title()} tại {destination}", label, 180_000, "Nên kiểm tra giờ mở cửa." )
            for label in labels
        ]


class WeatherAgent:
    """Nơi tích hợp Weather API trong giai đoạn tiếp theo."""

    def forecast(self, destination: str) -> str:
        return f"Dự báo tại {destination}: thời tiết thuận lợi; nên chuẩn bị áo mưa gọn nhẹ."


class BudgetAgent:
    def allocate(self, total_budget: int, days: int) -> int:
        return max(1, total_budget // max(days, 1))


class MemoryAgent:
    def preferences(self, traveler_id: str | None) -> list[str]:
        # Sẽ truy xuất PostgreSQL/Redis khi có tầng dữ liệu.
        return [] if not traveler_id else ["ưu tiên lịch trình linh hoạt"]

