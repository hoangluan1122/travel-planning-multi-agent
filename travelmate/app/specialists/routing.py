"""Exact small-day routing with directed road-time matrices and visit windows."""

import asyncio
import math
import time
from copy import deepcopy
from datetime import UTC, datetime
from itertools import permutations
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator, model_validator

from ..agents import AgentError, BaseAgent
from ..models import Context, Model


class RoutePoint(Model):
    id: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("id", mode="before")
    @classmethod
    def clean_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def numeric_coordinates(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Coordinates must be JSON numbers")
        return value


class Visit(RoutePoint):
    duration_minutes: int = Field(ge=1, le=1440, strict=True)
    opens_minute: int = Field(default=0, ge=0, le=1439, strict=True)
    closes_minute: int = Field(default=1440, ge=1, le=1440, strict=True)
    fixed_start_minute: int | None = Field(default=None, ge=0, le=1439, strict=True)

    @model_validator(mode="after")
    def window(self):
        if self.opens_minute >= self.closes_minute:
            raise ValueError("Opening time must precede closing time")
        if (
            self.fixed_start_minute is not None
            and not self.opens_minute <= self.fixed_start_minute < self.closes_minute
        ):
            raise ValueError("Fixed appointment must fall within visit window")
        return self


class Precedence(Model):
    before_id: str
    after_id: str


class RouteRequest(Model):
    origin: RoutePoint
    visits: list[Visit] = Field(min_length=1, max_length=8)
    departure_minute: int = Field(default=540, ge=0, le=1439, strict=True)
    finish_by_minute: int = Field(default=1080, ge=1, le=1440, strict=True)
    return_to_origin: bool = Field(default=True, strict=True)
    destination: RoutePoint | None = None
    travel_buffer_minutes: int = Field(default=0, ge=0, le=120, strict=True)
    optimize_order: bool = Field(default=True, strict=True)
    precedence: list[Precedence] = Field(default_factory=list, max_length=28)
    include_geometry: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def identities(self):
        ids = [self.origin.id] + [v.id for v in self.visits]
        if len(set(ids)) != len(ids):
            raise ValueError("Route IDs must be unique")
        if self.departure_minute >= self.finish_by_minute:
            raise ValueError("Departure must precede finish")
        if self.destination is not None:
            if self.return_to_origin or self.destination.id in ids:
                raise ValueError("Separate endpoint requires no return and a unique ID")
        visit_ids = {v.id for v in self.visits}
        pairs = {(p.before_id, p.after_id) for p in self.precedence}
        if len(pairs) != len(self.precedence):
            raise ValueError("Duplicate precedence")
        graph = {identity: set() for identity in visit_ids}
        for before, after in pairs:
            if before not in visit_ids or after not in visit_ids or before == after:
                raise ValueError("Precedence must refer to distinct visit IDs")
            graph[after].add(before)
        while graph:
            ready = {key for key, dependencies in graph.items() if not dependencies}
            if not ready:
                raise ValueError("Precedence cycle")
            graph = {key: deps - ready for key, deps in graph.items() if key not in ready}
        return self


class SnappedPoint(Model):
    point_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    distance_m: float = Field(ge=0, le=200.01)


class RouteMatrix(Model):
    point_ids: list[str]
    durations_seconds: list[list[float | None]]
    source: str
    fetched_at: datetime
    distances_m: list[list[float | None]] | None = None
    snapped_points: list[SnappedPoint] = Field(default_factory=list)
    profile: Literal["driving"] = "driving"

    @field_validator("durations_seconds", "distances_m", mode="before")
    @classmethod
    def actual_numbers(cls, value):
        if value is not None:
            if not isinstance(value, list) or any(not isinstance(row, list) for row in value):
                raise ValueError("Matrix must contain rows")
            if any(
                v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)))
                for row in value
                for v in row
            ):
                raise ValueError("Matrix values must be JSON numbers or null")
        return value

    @model_validator(mode="after")
    def dimensions(self):
        n = len(self.point_ids)
        if len(set(self.point_ids)) != n or len(self.durations_seconds) != n:
            raise ValueError("Invalid matrix size or IDs")
        for row in self.durations_seconds:
            if len(row) != n or any(v is not None and (not math.isfinite(v) or v < 0) for v in row):
                raise ValueError("Invalid matrix row")
        if self.distances_m is not None:
            if len(self.distances_m) != n or any(len(row) != n for row in self.distances_m):
                raise ValueError("Distance matrix dimensions mismatch")
            for i, row in enumerate(self.distances_m):
                for j, value in enumerate(row):
                    if value is not None and (not math.isfinite(value) or value < 0):
                        raise ValueError("Invalid distance")
                    if (value is None) != (self.durations_seconds[i][j] is None):
                        raise ValueError("Distance and duration reachability mismatch")
        if self.snapped_points and [p.point_id for p in self.snapped_points] != self.point_ids:
            raise ValueError("Snapped point identity mismatch")
        return self


class ScheduledVisit(Model):
    place_id: str
    arrival_second: float
    start_second: float
    end_second: float
    waiting_seconds: float = 0


class RouteLeg(Model):
    from_id: str
    to_id: str
    departure_second: float
    arrival_second: float
    driving_seconds: float
    buffer_seconds: float
    distance_m: float | None


class LineString(Model):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]] = Field(min_length=2, max_length=100000)

    @field_validator("coordinates", mode="before")
    @classmethod
    def numeric_coordinates(cls, value):
        if not isinstance(value, list) or any(
            not isinstance(point, (list, tuple))
            or len(point) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in point)
            for point in value
        ):
            raise ValueError("GeoJSON must contain numeric longitude/latitude pairs")
        return value

    @field_validator("coordinates")
    @classmethod
    def geo_bounds(cls, value):
        if any(not (-180 <= lon <= 180 and -90 <= lat <= 90) for lon, lat in value):
            raise ValueError("Invalid GeoJSON coordinates")
        return value


class RoadPath(Model):
    point_ids: list[str]
    geometry: LineString
    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    leg_durations_seconds: list[float]
    leg_distances_m: list[float]
    fetched_at: datetime
    source: str

    @model_validator(mode="after")
    def valid_legs(self):
        if len(self.leg_durations_seconds) != len(self.point_ids) - 1 or len(self.leg_distances_m) != len(
            self.leg_durations_seconds
        ):
            raise ValueError("Path leg dimensions mismatch")
        if any(v < 0 for v in self.leg_durations_seconds + self.leg_distances_m):
            raise ValueError("Negative path metrics")
        if abs(sum(self.leg_durations_seconds) - self.duration_seconds) > len(self.leg_durations_seconds):
            raise ValueError("Path duration total mismatch")
        if abs(sum(self.leg_distances_m) - self.distance_m) > len(self.leg_distances_m):
            raise ValueError("Path distance total mismatch")
        return self


class RouteReport(Model):
    status: Literal["feasible", "infeasible"]
    schedule: list[ScheduledVisit]
    travel_seconds: float | None
    baseline_travel_seconds: float | None
    baseline_feasible: bool
    saved_travel_seconds: float | None
    finish_second: float | None
    matrix: RouteMatrix
    evaluated_orders: int
    warnings: list[str]
    legs: list[RouteLeg] = Field(default_factory=list)
    total_distance_m: float | None = None
    waiting_seconds: float | None = None
    buffer_seconds: float | None = None
    geometry_status: Literal["not_requested", "available", "unavailable", "mismatch", "not_applicable"] = (
        "not_requested"
    )
    path: RoadPath | None = None
    objective: Literal["minimum_driving_seconds"] = "minimum_driving_seconds"
    attribution: str = "OSRM / © OpenStreetMap contributors, ODbL — https://www.openstreetmap.org/copyright"
    infeasibility_reasons: list[str] = Field(default_factory=list)


class OSRMProvider:
    def __init__(self, base_url="https://router.project-osrm.org", transport=None):
        # Server config only. Never accept provider URLs from an untrusted request.
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Invalid OSRM server configuration")
        self.base_url, self.transport = base_url.rstrip("/"), transport
        self._lock = asyncio.Lock()
        self._cache = {}
        self._last_request = 0.0
        self._cooldown_until = 0.0

    async def _get(self, service, points, params):
        coordinates = ";".join(f"{p.longitude},{p.latitude}" for p in points)
        url = f"{self.base_url}/{service}/v1/driving/{coordinates}"
        key = (url, tuple(sorted(params.items())))
        async with self._lock:
            now = time.monotonic()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if key in self._cache:
                _, data, fetched = self._cache[key]
                return deepcopy(data), fetched
            if now < self._cooldown_until:
                raise AgentError("Routing provider cooldown active")
            await asyncio.sleep(max(0, 1.1 - (now - self._last_request)))
            self._last_request = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=20,
                    transport=self.transport,
                    follow_redirects=False,
                    headers={"User-Agent": "TravelMateResearch/0.1"},
                ) as client:
                    async with client.stream("GET", url, params=params) as response:
                        if response.status_code == 429:
                            self._cooldown_until = time.monotonic() + 30
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 5_000_000:
                                raise ValueError("Routing response exceeds limit")
                import json

                data = json.loads(body)
                if not isinstance(data, dict) or data.get("code") != "Ok":
                    raise ValueError("Provider could not route")
            except httpx.TimeoutException:
                raise TimeoutError("Road routing timed out") from None
            except (httpx.HTTPError, TypeError, ValueError):
                raise AgentError("Road routing unavailable or invalid") from None
            fetched = datetime.now(UTC)
            if len(self._cache) >= 64:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + 60, deepcopy(data), fetched)
            return data, fetched

    def _snaps(self, raw, points):
        if not isinstance(raw, list) or len(raw) != len(points):
            raise ValueError("Missing snapped waypoints")
        snapped = []
        for item, point in zip(raw, points, strict=True):
            lon, lat = item["location"]
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) for v in [lon, lat, item["distance"]]
            ):
                raise ValueError("Invalid waypoint numbers")
            snapped.append(
                SnappedPoint(
                    point_id=point.id,
                    latitude=lat,
                    longitude=lon,
                    distance_m=item["distance"],
                )
            )
        return snapped

    async def matrix(self, points):
        try:
            data, fetched = await self._get(
                "table",
                points,
                {
                    "annotations": "duration,distance",
                    "radiuses": ";".join("200" for _ in points),
                },
            )
            snaps = self._snaps(data["sources"], points)
            self._snaps(data["destinations"], points)
            return RouteMatrix(
                point_ids=[p.id for p in points],
                durations_seconds=data["durations"],
                distances_m=data["distances"],
                snapped_points=snaps,
                source=self.base_url,
                fetched_at=fetched,
            )
        except (KeyError, TypeError, ValueError):
            raise AgentError("Road-time matrix unavailable or invalid") from None

    async def route(self, points):
        try:
            data, fetched = await self._get(
                "route",
                points,
                {
                    "alternatives": "false",
                    "steps": "false",
                    "geometries": "geojson",
                    "overview": "full",
                    "radiuses": ";".join("200" for _ in points),
                    "continue_straight": "false",
                },
            )
            self._snaps(data["waypoints"], points)
            route = data["routes"][0]
            legs = route["legs"]
            if len(legs) != len(points) - 1:
                raise ValueError("Geometry leg count mismatch")
            numbers = [route["duration"], route["distance"]] + [
                v for leg in legs for v in (leg["duration"], leg["distance"])
            ]
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                for v in numbers
            ):
                raise ValueError("Invalid route metrics")
            if abs(sum(leg["duration"] for leg in legs) - route["duration"]) > len(legs):
                raise ValueError("Geometry duration mismatch")
            if abs(sum(leg["distance"] for leg in legs) - route["distance"]) > len(legs):
                raise ValueError("Geometry distance mismatch")
            return RoadPath(
                point_ids=[p.id for p in points],
                geometry=route["geometry"],
                distance_m=route["distance"],
                duration_seconds=route["duration"],
                leg_durations_seconds=[leg["duration"] for leg in legs],
                leg_distances_m=[leg["distance"] for leg in legs],
                fetched_at=fetched,
                source=self.base_url,
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise AgentError("Road geometry unavailable or invalid") from None


def schedule_order(data, matrix, order):
    positions = {data.visits[index - 1].id: rank for rank, index in enumerate(order)}
    if any(positions[p.before_id] >= positions[p.after_id] for p in data.precedence):
        return None
    current = data.departure_minute * 60.0
    travel = 0.0
    previous = 0
    schedule = []
    for index in order:
        duration = matrix.durations_seconds[previous][index]
        if duration is None:
            return None
        visit = data.visits[index - 1]
        travel += duration
        arrival = current + duration + data.travel_buffer_minutes * 60
        start = max(arrival, visit.opens_minute * 60)
        if visit.fixed_start_minute is not None:
            if arrival > visit.fixed_start_minute * 60:
                return None
            start = visit.fixed_start_minute * 60
        current = start + visit.duration_minutes * 60
        if current > min(visit.closes_minute, data.finish_by_minute) * 60:
            return None
        schedule.append(
            ScheduledVisit(
                place_id=visit.id,
                arrival_second=arrival,
                start_second=start,
                end_second=current,
                waiting_seconds=start - arrival,
            )
        )
        previous = index
    terminal = (
        0 if data.return_to_origin else (len(data.visits) + 1 if data.destination is not None else None)
    )
    if terminal is not None:
        duration = matrix.durations_seconds[previous][terminal]
        if duration is None:
            return None
        current += duration + data.travel_buffer_minutes * 60
        travel += duration
    if current > data.finish_by_minute * 60:
        return None
    return travel, current, schedule


def route_points(data):
    return [data.origin, *data.visits] + ([data.destination] if data.destination is not None else [])


def route_legs(data, matrix, schedule):
    ids = matrix.point_ids
    indices = {identity: index for index, identity in enumerate(ids)}
    current, previous = data.departure_minute * 60.0, 0
    legs = []
    for visit in schedule:
        target = indices[visit.place_id]
        seconds = matrix.durations_seconds[previous][target]
        legs.append(
            RouteLeg(
                from_id=ids[previous],
                to_id=ids[target],
                departure_second=current,
                arrival_second=visit.arrival_second,
                driving_seconds=seconds,
                buffer_seconds=data.travel_buffer_minutes * 60,
                distance_m=matrix.distances_m[previous][target] if matrix.distances_m is not None else None,
            )
        )
        current, previous = visit.end_second, target
    terminal = 0 if data.return_to_origin else (len(ids) - 1 if data.destination is not None else None)
    if terminal is not None:
        seconds = matrix.durations_seconds[previous][terminal]
        legs.append(
            RouteLeg(
                from_id=ids[previous],
                to_id=ids[terminal],
                departure_second=current,
                arrival_second=current + seconds + data.travel_buffer_minutes * 60,
                driving_seconds=seconds,
                buffer_seconds=data.travel_buffer_minutes * 60,
                distance_m=matrix.distances_m[previous][terminal] if matrix.distances_m is not None else None,
            )
        )
    return legs


def optimize(data: RouteRequest, matrix: RouteMatrix):
    if matrix.point_ids != [p.id for p in route_points(data)]:
        raise AgentError("Matrix does not match route points")
    indices = tuple(range(1, len(data.visits) + 1))
    baseline = schedule_order(data, matrix, indices)
    best = None
    count = 0
    for order in permutations(indices) if data.optimize_order else [indices]:
        count += 1
        candidate = schedule_order(data, matrix, order)
        if candidate is not None and (best is None or candidate[:2] < best[:2]):
            best = candidate
    legs = route_legs(data, matrix, best[2]) if best else []
    return RouteReport(
        status="feasible" if best else "infeasible",
        schedule=best[2] if best else [],
        travel_seconds=best[0] if best else None,
        finish_second=best[1] if best else None,
        baseline_travel_seconds=baseline[0] if baseline else None,
        baseline_feasible=baseline is not None,
        saved_travel_seconds=baseline[0] - best[0] if baseline and best else None,
        matrix=matrix,
        evaluated_orders=count,
        legs=legs,
        total_distance_m=sum(leg.distance_m for leg in legs)
        if best and all(leg.distance_m is not None for leg in legs)
        else None,
        waiting_seconds=sum(visit.waiting_seconds for visit in best[2]) if best else None,
        buffer_seconds=sum(leg.buffer_seconds for leg in legs) if best else None,
        geometry_status="not_applicable" if not best else "not_requested",
        infeasibility_reasons=[]
        if best
        else ["Không có thứ tự nào thỏa đường đi, khung giờ, lịch hẹn và thời hạn ngày đã cung cấp."],
        warnings=[
            "Tối ưu thời gian lái xe theo ma trận tĩnh; không có giao thông realtime.",
            "Giờ mở cửa và thời lượng tham quan do đầu vào cung cấp, chưa xác minh nguồn.",
            "OSRM/OpenStreetMap; dịch vụ demo không có cam kết vận hành.",
        ],
    )


async def calculate_route(data, provider):
    raw = await provider.matrix(route_points(data))
    matrix = RouteMatrix.model_validate(raw.model_dump() if isinstance(raw, RouteMatrix) else raw)
    report = await asyncio.to_thread(optimize, data, matrix)
    if not data.include_geometry or report.status != "feasible":
        return report
    points = {p.id: p for p in route_points(data)}
    ordered = [data.origin] + [points[leg.to_id] for leg in report.legs]
    try:
        raw_path = await provider.route(ordered)
        path = RoadPath.model_validate(raw_path.model_dump() if isinstance(raw_path, RoadPath) else raw_path)
        if path.point_ids != [p.id for p in ordered] or len(path.leg_durations_seconds) != len(report.legs):
            raise AgentError("Route geometry identities mismatch")
        if any(
            abs(seconds - leg.driving_seconds) > max(2, leg.driving_seconds * 0.05)
            for seconds, leg in zip(path.leg_durations_seconds, report.legs, strict=True)
        ):
            report.geometry_status = "mismatch"
            report.warnings.append("Thời gian đường vẽ khác ma trận; cần tính lại trước khi ghép vào lịch.")
        else:
            report.geometry_status, report.path = "available", path
    except (AgentError, TimeoutError, AttributeError, ValueError):
        report.geometry_status = "unavailable"
        report.warnings.append(
            "Không lấy được đường vẽ; lịch hiện dựa trên ma trận, không tạo đường thay thế."
        )
    return report


class RouteSpecialist(BaseAgent[RouteRequest, RouteReport]):
    name, input_schema, output_schema = "route_specialist", RouteRequest, RouteReport

    def __init__(self, provider=None):
        self.provider = provider or OSRMProvider()

    async def execute(self, data, context):
        return await calculate_route(data, self.provider)


async def plan_road_route(request_json: str) -> dict:
    """ADK-callable driving route tool; coordinates/windows must come from input."""
    data = RouteRequest.model_validate_json(request_json)
    return (await RouteSpecialist().run(data, Context(), 50)).model_dump(mode="json")
