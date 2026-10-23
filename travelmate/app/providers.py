from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .agents import AgentError
from .models import Place, PlaceResult, PlaceSearchRequest, WeatherDay, WeatherResult


class DemoProvider:
    async def search_places(self, query):
        result = await self.search(query)
        result.places[0].id = f"demo-{query.category}"
        result.places[0].name = f"DEMO — {query.category} giả lập"
        return result

    async def search(self, trip):
        return PlaceResult(
            places=[
                Place(
                    id="demo-attraction",
                    name="DEMO — Điểm tham quan giả lập",
                    address=f"Dữ liệu thử nghiệm tại {trip.destination}",
                    latitude=16.05,
                    longitude=108.2,
                    source="fictional_fixture",
                )
            ],
            warnings=["DEMO: địa điểm giả lập, không dùng để đi du lịch thực tế."],
        )

    async def forecast(self, trip):
        return WeatherResult(warnings=["DEMO: chưa gọi dịch vụ thời tiết."])


class LiveProvider:
    def __init__(self, maps_key: str, transport=None):
        self.maps_key = maps_key
        self.transport = transport

    async def search(self, trip):
        return await self.search_places(PlaceSearchRequest(destination=trip.destination))

    async def search_places(self, query: PlaceSearchRequest):
        labels = {"attraction": "Tourist attractions", "hotel": "Hotels", "restaurant": "Restaurants"}
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
                response = await client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers={
                        "X-Goog-Api-Key": self.maps_key,
                        "X-Goog-FieldMask": (
                            "places.id,places.displayName,places.formattedAddress,"
                            "places.location,places.types"
                        ),
                    },
                    json={
                        "textQuery": (
                            f"{labels[query.category]}"
                            f"{' ' + query.keyword.strip() if query.keyword.strip() else ''}"
                            f" in {query.destination}"
                        ),
                        "pageSize": query.limit,
                        "languageCode": "vi",
                    },
                )
                response.raise_for_status()
            raw = response.json().get("places", [])
            if not isinstance(raw, list):
                raise ValueError("Invalid places collection")
        except httpx.TimeoutException:
            raise TimeoutError("Place lookup timed out") from None
        except (httpx.HTTPError, ValueError, AttributeError):
            raise AgentError("Place service unavailable or returned invalid data") from None
        places, seen = [], set()
        warnings = ["Giá, tình trạng phòng, giờ mở cửa và tuyến di chuyển chưa xác minh."]
        fetched_at = datetime.now(UTC)
        for item in raw[: query.limit]:
            try:
                place = Place(
                    id=item["id"],
                    name=item["displayName"]["text"],
                    address=item.get("formattedAddress", ""),
                    latitude=item["location"]["latitude"],
                    longitude=item["location"]["longitude"],
                    source="google_places",
                    types=item.get("types", []),
                    fetched_at=fetched_at,
                )
                if not place.id.strip() or not place.name.strip():
                    raise ValueError("Empty identity")
            except (KeyError, TypeError, ValueError, ValidationError):
                warnings.append("Bỏ qua một địa điểm có dữ liệu không hợp lệ.")
                continue
            if place.id not in seen:
                seen.add(place.id)
                places.append(place)
        if raw and not places:
            raise AgentError("Place service returned no usable records")
        if not places:
            warnings.append("Không tìm thấy địa điểm phù hợp; thử tên thành phố và quốc gia.")
        return PlaceResult(places=places, warnings=warnings)

    async def get_details(self, place_id: str):
        """Fetch identity/location details only; no price or availability claims."""
        if not place_id or len(place_id) > 300:
            raise AgentError("Invalid place ID")
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
                response = await client.get(
                    f"https://places.googleapis.com/v1/places/{quote(place_id, safe='')}",
                    headers={
                        "X-Goog-Api-Key": self.maps_key,
                        "X-Goog-FieldMask": "id,displayName,formattedAddress,location,types",
                    },
                    params={"languageCode": "vi"},
                )
                response.raise_for_status()
            item = response.json()
            place = Place(
                id=item["id"],
                name=item["displayName"]["text"],
                address=item.get("formattedAddress", ""),
                latitude=item["location"]["latitude"],
                longitude=item["location"]["longitude"],
                types=item.get("types", []),
                source="google_places",
                fetched_at=datetime.now(UTC),
            )
            if place.id != place_id or not place.name.strip():
                raise ValueError("Mismatched identity")
            return place
        except httpx.TimeoutException:
            raise TimeoutError("Place details timed out") from None
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise AgentError("Place details unavailable or invalid") from None

    async def forecast(self, trip):
        if trip.start_date > date.today() + timedelta(days=15):
            return WeatherResult(warnings=["Chuyến đi nằm ngoài phạm vi dự báo 16 ngày."])
        async with httpx.AsyncClient(timeout=15) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": trip.destination, "count": 1},
            )
            geo.raise_for_status()
            candidates = geo.json().get("results", [])
            if not candidates:
                raise AgentError("Cannot resolve destination for weather")
            location = candidates[0]
            result = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "daily": "weather_code",
                    "timezone": "auto",
                    "forecast_days": 16,
                },
            )
            result.raise_for_status()
        daily = result.json()["daily"]
        days = [
            WeatherDay(date=d, weather_code=c)
            for d, c in zip(daily["time"], daily["weather_code"], strict=True)
            if c is not None and trip.start_date <= date.fromisoformat(d) <= trip.end_date
        ]
        warnings = ["Nguồn: Open-Meteo; cần kiểm tra đúng địa danh được tra cứu."]
        if len(days) != (trip.end_date - trip.start_date).days + 1:
            warnings.append("Một số ngày chưa có dự báo.")
        return WeatherResult(days=days, warnings=warnings)
