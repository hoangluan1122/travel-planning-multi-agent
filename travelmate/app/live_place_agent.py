"""One runnable Place agent: live discovery, source validation and JSON export.

The tool_workflow engine is a bounded deterministic agent workflow. The optional
adk_llm engine delegates search/refinement/selection to the existing ADK agent.
Neither engine reads example/evaluation files or falls back to demo records.
"""

import argparse
import asyncio
import hashlib
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .agents import AgentError, BaseAgent
from .browser_places import BrowserPlaceResult, WebSource
from .geo_places import GeoPlaceService, Locality, LocalityChoiceRequired, PlaceMetadata
from .models import Context, Model, Place, PlaceResult, PlaceSearchRequest
from .place_agent import PlaceAgentInput, PlaceAssistant
from .structured_hotel import URL_PATTERN, StructuredHotelReader

logger = logging.getLogger(__name__)


class LivePlaceRequest(Model):
    destination: str = Field(min_length=2, max_length=120)
    category: Literal["hotel", "restaurant", "attraction"] = "hotel"
    keyword: str = Field(default="", max_length=120)
    needs: str = Field(default="", max_length=1500)
    limit: int = Field(default=5, ge=1, le=20, strict=True)
    radius_m: int = Field(default=3000, ge=250, le=10000, strict=True)
    search_scope: Literal["auto", "nearby", "area", "country"] = "auto"
    location_id: str | None = Field(
        default=None,
        pattern=r"^(?:geonames:\d+|vn:(?:country|(?:current|legacy):[A-Za-z0-9]+)|photon:(?:node|way|relation)/\d+)$",
        max_length=100,
    )
    offset: int = Field(default=0, ge=0, le=500, strict=True)

    @model_validator(mode="after")
    def clean_input(self):
        self.destination = " ".join(self.destination.split())
        self.keyword = " ".join(self.keyword.split())
        self.needs = self.needs.strip()
        if len(self.destination) < 2:
            raise ValueError("Provide a specific locality of at least two characters")
        return self


class PlaceTrace(Model):
    step: Literal["search", "validate", "details", "complete", "failed"]
    at: datetime
    message: str
    record_count: int = 0


class LivePlaceReport(Model):
    request_id: UUID
    status: Literal[
        "success", "partial", "no_results", "needs_location", "source_error", "blocked", "timeout"
    ]
    execution_mode: Literal["tool_workflow", "adk_llm"]
    data_origin: Literal["live_network"] = "live_network"
    destination: str
    category: Literal["hotel", "restaurant", "attraction"] = "hotel"
    resolved_location: Locality | None = None
    location_options: list[Locality] = Field(default_factory=list)
    place_metadata: dict[str, PlaceMetadata] = Field(default_factory=dict)
    candidate_count: int = 0
    offset: int = 0
    has_more: bool = False
    applied_radius_m: int | None = None
    suggested_radius_m: int | None = None
    retrieval_exhaustive: Literal[False] = False
    started_at: datetime
    completed_at: datetime
    places: list[Place]
    sources: list[WebSource]
    search_calls: int
    detail_calls: int
    requirements_verified: Literal[False] = False
    missing_fields: list[str]
    trace: list[PlaceTrace]
    warnings: list[str]

    @model_validator(mode="after")
    def status_matches_evidence(self):
        if self.status in {"success", "partial"} and not self.places:
            raise ValueError("Successful report requires sourced Place records")
        if (
            self.status in {"source_error", "blocked", "timeout", "no_results", "needs_location"}
            and self.places
        ):
            raise ValueError("Failed report cannot contain usable records")
        if len({p.id for p in self.places}) != len(self.places):
            raise ValueError("Duplicate output Place IDs")
        return self


class GroundedBrowserProvider:
    """Per-invocation evidence store and real tools for either execution engine."""

    def __init__(self, request, context, web_tool, reader):
        self.request, self.context = request, context
        self.web_tool, self.reader = web_tool, reader
        self.records = {}
        self.sources = {}
        self.trace = []
        self.warnings = []
        self.search_calls = self.detail_calls = 0
        self.last_source_status = "source_error"
        self.queries = set()

    def event(self, step, message, count=0):
        self.trace.append(PlaceTrace(step=step, at=datetime.now(UTC), message=message, record_count=count))

    def validate_record(self, raw):
        place = Place.model_validate(raw.model_dump() if isinstance(raw, Place) else raw)
        if not place.source_url or not URL_PATTERN.fullmatch(place.source_url):
            raise AgentError("Place is outside the reviewed source adapter")
        if place.source_url not in self.sources:
            raise AgentError("Place URL was not discovered during this invocation")
        if place.id != "official:" + hashlib.sha256(place.source_url.encode()).hexdigest()[:24]:
            raise AgentError("Place identity does not match its canonical URL")
        if place.source != "official_mgallery_jsonld" or "hotel" not in place.types:
            raise AgentError("Unsupported source/category")
        if place.fetched_at is None or place.fetched_at.tzinfo is None:
            raise AgentError("Place needs an aware source retrieval timestamp")
        age = (datetime.now(UTC) - place.fetched_at).total_seconds()
        if age < -60 or age > 900:
            raise AgentError("Place evidence is stale or from a future clock")
        for field in ["name", "address", "latitude", "longitude", "types"]:
            if place.field_sources.get(field) != place.source_url:
                raise AgentError("Core field provenance missing")
        if not place.address.strip():
            raise AgentError("Address missing")
        return place.model_copy(deep=True)

    async def search_places(self, query):
        if query.destination != self.request.destination or query.category != "hotel":
            raise AgentError("Search cannot change the fixed destination/category")
        if query.keyword in self.queries:
            raise AgentError("Same query already executed; use existing evidence")
        if self.search_calls >= 2:
            raise AgentError("Live discovery budget exceeded")
        self.search_calls += 1
        self.queries.add(query.keyword)
        self.last_source_status = "source_error"
        self.event("search", "Tìm nguồn trực tiếp và đọc các website có adapter được hỗ trợ.")
        raw = await self.web_tool.run(query, self.context, 60)
        discovery = BrowserPlaceResult.model_validate(raw.model_dump())
        self.last_source_status = discovery.status
        self.warnings.extend(discovery.warnings)
        self.sources.update({source.url: source for source in discovery.sources})
        accepted = []
        for raw_place in discovery.places:
            try:
                place = self.validate_record(raw_place)
            except (AgentError, ValueError):
                self.warnings.append("Bỏ bản ghi thiếu nguồn, sai adapter hoặc không còn đủ bằng chứng.")
                continue
            if place.id not in {p.id for p in accepted}:
                accepted.append(place)
                self.records[place.id] = place
        self.event(
            "validate", "Kiểm tra dữ liệu, URL nguồn, thời điểm lấy và nguồn của từng trường.", len(accepted)
        )
        if not accepted:
            raise AgentError("No source-validated records; not evidence that no hotels exist")
        return PlaceResult(places=accepted[: self.request.limit], warnings=discovery.warnings)

    async def get_details(self, place_id):
        if place_id not in self.records or self.detail_calls >= 2:
            raise AgentError("Unknown ID or details budget exceeded")
        self.detail_calls += 1
        known = self.records[place_id]
        self.event("details", "Đọc lại thông tin tại URL chính thức đã tìm thấy.")
        place = self.validate_record(await self.reader.read(known.source_url, self.request.destination))
        if place.id != place_id:
            raise AgentError("Source identity changed")
        self.records[place_id] = place
        return place


class GeoGroundedProvider:
    """Pinned locality and category; only source-observed IDs may leave the agent."""

    def __init__(self, request, service):
        self.request, self.service = request, service
        self.records, self.sources, self.metadata = {}, {}, {}
        self.trace, self.warnings = [], []
        self.search_calls = self.detail_calls = 0
        self.last_source_status = "source_error"
        self.location = None
        self.choices = []
        self.queries = set()
        self.candidate_count = 0

    def event(self, step, message, count=0):
        self.trace.append(PlaceTrace(step=step, at=datetime.now(UTC), message=message, record_count=count))

    async def resolve(self):
        self.event(
            "search", "Phân giải phạm vi Việt Nam: danh mục ranh giới có phiên bản hoặc công cụ địa danh."
        )
        self.location = await self.service.resolve(
            self.request.destination, self.request.location_id, self.request.search_scope
        )
        if self.location.coordinate_kind == "geometry_center" and self.location.scope == "nearby":
            self.warnings.append(
                "Điểm tham chiếu là tâm hình học của khu vực theo nguồn, không phải cửa vào. "
                "Kết quả chỉ nằm trong bán kính đã chọn quanh tâm này; không bao phủ toàn bộ khu du lịch."
            )
        if self.location.scope != "nearby":
            self.warnings.append(
                "Tìm theo polygon ranh giới tham chiếu, không áp dụng bán kính. Lấy mẫu có giới hạn qua các ô không gian, không phải toàn bộ địa điểm trong vùng."
            )
            if self.location.historical:
                self.warnings.append(
                    "Đang tìm khu vực cũ theo ranh giới tham chiếu năm 2020; không phải đơn vị hành chính hiện hành."
                )

    def validate_record(self, raw):
        place = Place.model_validate(raw.model_dump() if isinstance(raw, Place) else raw)
        # Compare the entire record with stored evidence, not just its ID or URL.
        known = self.records.get(place.id)
        if known is None or known.model_dump() != place.model_dump():
            raise AgentError("Output differs from source-observed evidence")
        return known.model_copy(deep=True)

    async def search_places(self, query):
        if query.destination != self.request.destination or query.category != self.request.category:
            raise AgentError("Destination/category is pinned")
        if self.search_calls >= 2 or query.keyword in self.queries:
            raise AgentError("Search budget exceeded or query already executed")
        if self.location is None:
            await self.resolve()
        self.search_calls += 1
        self.queries.add(query.keyword)
        self.event(
            "search",
            "Tra Photon/OSM theo loại địa điểm và "
            + (
                "bán kính đã chọn."
                if self.location.scope == "nearby"
                else "các ô bao phủ ranh giới tham chiếu."
            ),
        )
        self.last_source_status = "source_error"
        places, metadata, skipped = await self.service.discover(
            self.location,
            self.request.category,
            self.request.radius_m,
            query.keyword,
        )
        self.candidate_count = len(places)
        self.last_source_status = "success" if places else "no_results"
        self.metadata.update(metadata)
        if any(info.coverage_partial for info in metadata.values()):
            self.warnings.append("Một số ô tìm kiếm bị lỗi nguồn; kết quả chỉ là phần lấy được.")
        for place in places:
            self.records[place.id] = place
            self.sources[place.source_url] = WebSource(
                id=place.id,
                title=place.name,
                url=place.source_url,
                snippet=place.address,
                search_url=metadata[place.id].retrieval_url,
                fetched_at=place.fetched_at,
                verification="structured_source_record",
            )
        self.event(
            "validate",
            "Loại bản ghi thiếu tên, sai loại, ngoài phạm vi hoặc trùng; giữ tọa độ riêng và nguồn OSM.",
            len(places),
        )
        if skipped:
            self.warnings.append(f"Đã bỏ {skipped} bản ghi nguồn không hợp lệ.")
        start = self.request.offset
        page = places[start : start + self.request.limit]
        if not page:
            self.last_source_status = "no_results"
        return PlaceResult(places=page, warnings=[])

    async def get_details(self, place_id):
        if place_id not in self.records or self.detail_calls >= 2:
            raise AgentError("Unknown ID or detail budget exceeded")
        self.detail_calls += 1
        known = self.records[place_id]
        self.event("details", "Tra lại địa điểm theo tên, chỉ nhận đúng OSM ID đã tìm thấy.")
        places, metadata, _ = await self.service.discover(
            self.location,
            self.request.category,
            self.request.radius_m,
            known.name,
        )
        exact = next((p for p in places if p.id == place_id), None)
        if exact is None:
            raise AgentError("Exact ID not found on detail refresh")
        self.records[place_id] = exact
        self.metadata[place_id] = metadata[place_id]
        return exact.model_copy(deep=True)


class LivePlaceAgent(BaseAgent[LivePlaceRequest, LivePlaceReport]):
    name, input_schema, output_schema = "live_place_agent", LivePlaceRequest, LivePlaceReport

    def __init__(self, *, model_factory=None, web_tool=None, reader=None, geo_service=None):
        self.model_factory = model_factory
        self.web_tool = web_tool
        self.reader = reader or StructuredHotelReader()
        self.geo_service = geo_service or GeoPlaceService()

    async def execute(self, data, context):
        started = datetime.now(UTC)
        provider = (
            GroundedBrowserProvider(data, context, self.web_tool, self.reader)
            if self.web_tool is not None
            else GeoGroundedProvider(data, self.geo_service)
        )
        mode = "adk_llm" if self.model_factory else "tool_workflow"
        selected, failure = [], "source_error"
        try:
            if isinstance(provider, GeoGroundedProvider):
                await provider.resolve()
            if self.model_factory:
                agent = PlaceAssistant(self.model_factory, provider, max_llm_calls=8)
                output = await agent.run(
                    PlaceAgentInput(
                        destination=data.destination,
                        category=data.category,
                        keyword=data.keyword,
                        needs=data.needs,
                        limit=data.limit,
                        radius_m=data.radius_m,
                    ),
                    context,
                    130,
                )
                selected = [provider.validate_record(p) for p in output.places]
                provider.warnings.extend(output.warnings)
            else:
                # A failed keyword query can be broadened once, without changing locality.
                for keyword in dict.fromkeys([data.keyword, ""]):
                    try:
                        found = await provider.search_places(
                            PlaceSearchRequest(
                                destination=data.destination,
                                category=data.category,
                                limit=data.limit,
                                keyword=keyword,
                            )
                        )
                        selected = found.places
                        if not selected and keyword:
                            provider.warnings.append(
                                "Không thấy kết quả theo từ khóa; thử lại không có từ khóa trong cùng khu vực."
                            )
                            continue
                        break
                    except AgentError:
                        provider.warnings.append(
                            "Một lần truy vấn nguồn thất bại; lỗi nguồn không chứng minh địa điểm không tồn tại."
                        )
                        if provider.last_source_status in {"blocked", "timeout"}:
                            break
        except LocalityChoiceRequired as exc:
            provider.choices = exc.choices
            provider.warnings.append(exc.reason)
            failure = "needs_location"
        except TimeoutError:
            failure = "timeout"
        except AgentError:
            provider.warnings.append("Agent không hoàn tất được vòng xử lý; không thay bằng dữ liệu demo.")
        except Exception as exc:
            logger.warning("live_place request=%s error_type=%s", context.request_id, type(exc).__name__)
            provider.warnings.append(
                "Không thực thi được công cụ hoặc mô hình; xem cấu hình và khả năng truy cập nguồn."
            )
        if not selected:
            if provider.last_source_status in {"blocked", "timeout", "no_results"}:
                failure = provider.last_source_status
            provider.event(
                "failed",
                {
                    "needs_location": "Chờ người dùng xác nhận địa danh; chưa truy vấn địa điểm.",
                    "no_results": "Nguồn trả về nhưng chưa có ứng viên phù hợp ở trang và phạm vi đã chọn.",
                }.get(failure, "Chưa lấy được bản ghi đủ bằng chứng từ nguồn trực tiếp."),
            )
        else:
            provider.event(
                "complete", "Đã tạo các bản ghi Place có nguồn để hiển thị và xuất JSON.", len(selected)
            )
        warnings = provider.warnings + [
            "Dữ liệu cộng đồng OpenStreetMap qua Photon; chỉ mục có thể thiếu hoặc chậm cập nhật, không phải danh sách đầy đủ hay xác nhận đang mở cửa.",
            "Khoảng cách đường chim bay tính từ điểm tham chiếu của phạm vi đã chọn, không phải tuyến đường di chuyển. Tọa độ hình học không đảm bảo là cửa vào.",
            "Chưa xác minh giá theo ngày, phòng trống, ảnh có quyền sử dụng, giờ mở cửa hoặc các nhu cầu riêng.",
        ]
        if mode == "tool_workflow":
            warnings.append("Phiên này chạy workflow công cụ xác định, không gọi LLM.")
        location = getattr(provider, "location", None)
        nearby = location is not None and location.scope == "nearby"
        return LivePlaceReport(
            request_id=context.request_id,
            status=(
                "partial"
                if data.needs
                or provider.search_calls > 1
                or any(m.coverage_partial for m in getattr(provider, "metadata", {}).values())
                else "success"
            )
            if selected
            else failure,
            execution_mode=mode,
            destination=data.destination,
            category=data.category,
            resolved_location=getattr(provider, "location", None),
            location_options=getattr(provider, "choices", []),
            place_metadata={p.id: provider.metadata[p.id] for p in selected}
            if isinstance(provider, GeoGroundedProvider)
            else {},
            candidate_count=getattr(provider, "candidate_count", len(selected)),
            offset=data.offset,
            has_more=getattr(provider, "candidate_count", 0) > data.offset + data.limit,
            applied_radius_m=data.radius_m if nearby else None,
            suggested_radius_m=next(r for r in (1000, 3000, 5000, 10000) if r > data.radius_m)
            if nearby
            and failure == "no_results"
            and data.radius_m < 10000
            and getattr(provider, "candidate_count", 0) == 0
            and data.offset == 0
            else None,
            started_at=started,
            completed_at=datetime.now(UTC),
            places=selected,
            sources=list(provider.sources.values()),
            search_calls=provider.search_calls,
            detail_calls=provider.detail_calls,
            missing_fields=list(
                dict.fromkeys(
                    ["licensed_images", "operating_status", "needs_verification"]
                    + (
                        ["stay_price", "room_availability"]
                        if data.category == "hotel"
                        else ["visit_or_meal_price"]
                    )
                    + (
                        ["opening_hours"]
                        if not selected or any(not p.opening_hours_raw for p in selected)
                        else []
                    )
                    + (["street_address"] if any(not p.address for p in selected) else [])
                )
            ),
            trace=provider.trace,
            warnings=list(dict.fromkeys(warnings)),
        )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--keyword", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--category", choices=["hotel", "restaurant", "attraction"], default="hotel")
    parser.add_argument("--radius-m", type=int, default=3000)
    parser.add_argument("--location-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = await LivePlaceAgent().run(
        LivePlaceRequest(
            destination=args.destination,
            keyword=args.keyword,
            limit=args.limit,
            category=args.category,
            radius_m=args.radius_m,
            location_id=args.location_id,
        ),
        Context(),
        140,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2))
    if result.status not in {"success", "partial"}:
        raise SystemExit(2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
