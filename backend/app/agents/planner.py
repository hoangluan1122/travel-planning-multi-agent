from datetime import timedelta
from app.schemas import Activity, ItineraryDay, TripPlan, TripRequest
from .specialists import BudgetAgent, MemoryAgent, PlaceAgent, WeatherAgent


class PlannerAgent:
    """Điều phối các specialist agent để tạo lịch trình khả dụng ban đầu."""

    def __init__(self):
        self.place_agent = PlaceAgent()
        self.weather_agent = WeatherAgent()
        self.budget_agent = BudgetAgent()
        self.memory_agent = MemoryAgent()

    def plan(self, request: TripRequest) -> TripPlan:
        days = (request.end_date - request.start_date).days + 1
        remembered = self.memory_agent.preferences(request.traveler_id)
        places = self.place_agent.find_places(request.destination, request.interests)
        daily_limit = self.budget_agent.allocate(request.budget, days)
        itinerary = []
        for index in range(days):
            place = places[index % len(places)]
            activities = [
                Activity(time="09:00", title=place.name, category=place.category, estimated_cost=place.cost, note=place.note),
                Activity(time="18:00", title="Khám phá ẩm thực địa phương", category="ẩm thực", estimated_cost=min(250_000, daily_limit // 3), note="Ưu tiên lựa chọn gần điểm tham quan."),
            ]
            itinerary.append(ItineraryDay(day=index + 1, date=request.start_date + timedelta(days=index), activities=activities))
        estimated = sum(activity.estimated_cost for day in itinerary for activity in day.activities)
        return TripPlan(destination=request.destination, total_budget=request.budget, estimated_cost=estimated, weather_summary=self.weather_agent.forecast(request.destination), itinerary=itinerary, recommendations=["Kiểm tra lại chi phí vé và lưu trú trước khi đặt.", *remembered])

