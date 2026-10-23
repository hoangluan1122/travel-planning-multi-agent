"""One manual audit, capped public-source traffic. No mock POIs; no production changes.

Exercises the real FastAPI handlers in-process with the real agent and HTTP network
transport. Catalog checks are local. Live cases are representative, not exhaustive.
"""

import asyncio
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.geo_places import GeoPlaceService, PublicGeoClient
from app.live_place_agent import LivePlaceAgent, LivePlaceReport
from app.live_place_api import LivePlaceSettings, create_app
from app.vietnam_regions import load_catalog, name_key

# Expected province is an independent boundary oracle; never an input substitute
# for a failed locality lookup. A wrong/ambiguous locality is reported, not rescued.
CASES = [
    ("Hà Nội", "Hà Nội"),
    ("Cao Bằng", "Cao Bằng"),
    ("Tuyên Quang", "Đồng Văn"),
    ("Lào Cai", "Sa Pa"),
    ("Điện Biên", "Điện Biên Phủ"),
    ("Lai Châu", "Lai Châu"),
    ("Sơn La", "Mộc Châu"),
    ("Thái Nguyên", "Bắc Kạn"),
    ("Lạng Sơn", "Lạng Sơn"),
    ("Quảng Ninh", "Hạ Long"),
    ("Phú Thọ", "Tam Đảo"),
    ("Bắc Ninh", "Bắc Giang"),
    ("Hải Phòng", "Cát Bà"),
    ("Hưng Yên", "Thái Bình"),
    ("Ninh Bình", "Tràng An"),
    ("Thanh Hóa", "Sầm Sơn"),
    ("Nghệ An", "Cửa Lò"),
    ("Hà Tĩnh", "Thiên Cầm"),
    ("Quảng Trị", "Phong Nha"),
    ("Huế", "Huế"),
    ("Đà Nẵng", "Hội An"),
    ("Quảng Ngãi", "Lý Sơn"),
    ("Khánh Hòa", "Nha Trang"),
    ("Gia Lai", "Quy Nhơn"),
    ("Đắk Lắk", "Tuy Hòa"),
    ("Lâm Đồng", "Đà Lạt"),
    ("Tây Ninh", "Tây Ninh"),
    ("Đồng Nai", "Đồng Xoài"),
    ("Hồ Chí Minh", "Vũng Tàu"),
    ("Vĩnh Long", "Bến Tre"),
    ("Đồng Tháp", "Mỹ Tho"),
    ("An Giang", "Phú Quốc"),
    ("Cần Thơ", "Sóc Trăng"),
    ("Cà Mau", "Bạc Liêu"),
    ("Đà Nẵng", "Bà Nà Hills"),
    ("Lào Cai", "Fansipan"),
    ("Hồ Chí Minh", "Côn Đảo"),
    ("Lâm Đồng", "Mũi Né"),
    ("Đà Nẵng", "Thánh địa Mỹ Sơn"),
    ("Ninh Bình", "Vườn quốc gia Cúc Phương"),
]


class AuditTransport(httpx.AsyncBaseTransport):
    """Actual HTTP, modest hard cap, raw evidence and stop-on-throttle circuit."""

    def __init__(self, output):
        self.output, self.logs = output, []
        self.counts = Counter()
        self.stop_reason = None

    async def handle_async_request(self, request):
        host = request.url.host
        limit = 60 if host == "photon.komoot.io" else 45
        if self.stop_reason or self.counts[host] >= limit:
            self.stop_reason = self.stop_reason or f"request_budget:{host}:{limit}"
            raise httpx.RequestError("Audit stopped at its public-source budget", request=request)
        self.counts[host] += 1
        started = time.monotonic()
        log = dict(number=len(self.logs) + 1, url=str(request.url), at=datetime.now(UTC).isoformat())
        self.logs.append(log)
        try:
            async with httpx.AsyncHTTPTransport(retries=0) as transport:
                response = await transport.handle_async_request(request)
                body = bytearray()
                async for chunk in response.aiter_raw():
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        raise httpx.RequestError("Audit response too large", request=request)
            log.update(status=response.status_code, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            log["content_encoding"] = response.headers.get("content-encoding", "identity")
            (self.output / "network" / f"{log['number']:03d}.bin").write_bytes(body)
            if response.status_code in {403, 429}:
                self.stop_reason = f"upstream_throttle_or_block:{host}:{response.status_code}"
            return httpx.Response(
                response.status_code, headers=response.headers, content=bytes(body), request=request
            )
        except httpx.HTTPError as exc:
            log["error_type"] = type(exc).__name__
            raise
        finally:
            log["elapsed_s"] = round(time.monotonic() - started, 3)

    async def aclose(self):
        pass  # Each real underlying transport is already closed inside the call.


def expected_region(name):
    matches = [r for r in load_catalog().matches(name) if not r["historical"]]
    if len(matches) != 1:
        raise ValueError(f"Invalid audit province oracle: {name}")
    return matches[0]


def source_errors(data, radius_m=5000):
    errors = []
    try:
        report = LivePlaceReport.model_validate(data)
    except ValueError:
        return ["invalid_report_schema"]
    for place in report.places:
        if place.source != "osm_photon" or not place.source_url or not place.id.startswith("osm:"):
            errors.append("invalid_source_identity")
        elif place.source_url != "https://www.openstreetmap.org/" + place.id.removeprefix("osm:"):
            errors.append("id_url_mismatch")
        if not place.fetched_at or (datetime.now(UTC) - place.fetched_at).total_seconds() > 900:
            errors.append("missing_or_stale_timestamp")
        if any(
            place.field_sources.get(field) != place.source_url
            for field in ["name", "latitude", "longitude", "types"]
        ):
            errors.append("missing_field_provenance")
        info = report.place_metadata.get(place.id)
        if not info or info.distance_m > radius_m:
            errors.append("outside_test_radius")
    return sorted(set(errors))


async def audit_case(client, case, index, output):
    province, destination = case
    category = ["hotel", "restaurant", "attraction"][index % 3]
    expected = expected_region(province)
    result = dict(
        number=index + 1,
        province=province,
        destination=destination,
        category=category,
        outcome="not_run",
        elapsed_s=0,
        records=0,
        status="",
        evidence_errors=[],
        selected_by_test=False,
    )
    started = time.monotonic()
    payload = dict(destination=destination, category=category, search_scope="nearby", radius_m=5000, limit=5)
    first = await client.post("/api/v1/places/live", json=payload)
    data = first.json()
    (output / "api" / f"{index + 1:02d}-initial.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if data.get("status") == "needs_location":
        options = data.get("location_options", [])
        exact = [
            p
            for p in options
            if name_key(p["name"]) == name_key(destination)
            and load_catalog().contains(expected["id"], p["longitude"], p["latitude"])
        ]
        if len(exact) == 1:
            # Deliberate test selection with a declared geography oracle; not arbitrary first result.
            payload["location_id"] = exact[0]["id"]
            result["selected_by_test"] = True
            response = await client.post("/api/v1/places/live", json=payload)
            data = response.json()
        else:
            result["outcome"] = "needs_manual_choice" if options else "unresolved_locality"
            result["options"] = [
                dict(id=p["id"], name=p["name"], admin1=p["admin1"], admin2=p["admin2"]) for p in options
            ]
    location = data.get("resolved_location")
    if location and not load_catalog().contains(expected["id"], location["longitude"], location["latitude"]):
        result["outcome"] = "geographic_mismatch"
    elif result["outcome"] == "not_run":
        if data.get("status") in {"success", "partial"} and data.get("places"):
            errors = source_errors(data)
            result["evidence_errors"] = errors
            result["outcome"] = "invalid_evidence" if errors else "usable_sourced_records"
        else:
            result["outcome"] = {
                "no_results": "no_indexed_results",
                "source_error": "source_error",
                "timeout": "timeout",
            }.get(data.get("status"), "api_error")
    result.update(
        status=data.get("status", str(first.status_code)),
        elapsed_s=round(time.monotonic() - started, 2),
        records=len(data.get("places", [])),
        names=[p["name"] for p in data.get("places", [])],
        request_id=data.get("request_id"),
        resolved_location=location,
    )
    (output / "api" / f"{index + 1:02d}-final.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def write_report(output, catalog_results, cases, transport):
    counts = Counter(r["outcome"] for r in cases)
    payload = dict(
        at=datetime.now(UTC).isoformat(),
        catalog_checks=catalog_results,
        live_cases=cases,
        outcomes=dict(counts),
        planned_live_cases=len(CASES),
        not_run=len(CASES) - len(cases),
        stop_reason=transport.stop_reason,
        network_requests=dict(transport.counts),
        exhaustive=False,
        llm_called=False,
    )
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "network-log.json").write_text(
        json.dumps(transport.logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output / "cases.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "number",
                "province",
                "destination",
                "category",
                "outcome",
                "status",
                "records",
                "elapsed_s",
                "selected_by_test",
            ],
        )
        writer.writeheader()
        writer.writerows({k: r.get(k) for k in writer.fieldnames} for r in cases)
    lines = [
        "# Báo cáo kiểm tra Place Agent trên phạm vi Việt Nam",
        "",
        f"Thời điểm UTC: {payload['at']}",
        "",
        "## Phạm vi và cách đọc kết quả",
        "",
        f"- Danh mục: {len(catalog_results)} khu vực kiểm tra cục bộ qua API; đây KHÔNG phải kiểm thử POI mạng thật của 97 vùng.",
        f"- Dữ liệu thật: {len(cases)}/{len(CASES)} ca chạy FastAPI → agent → HTTP thật; không mock dữ liệu nguồn, không gọi Gemini.",
        "- Bộ ca có một điểm đại diện cho mỗi tỉnh/thành trong danh mục 34, thêm 6 khu du lịch; loại lưu trú/ăn uống/tham quan được luân phiên, không phải đủ ba loại cho mỗi nơi.",
        "- Với địa danh trùng, chỉ chọn khi có đúng một tên khớp trong polygon tỉnh tham chiếu. Những lựa chọn khác được giữ ở needs_manual_choice, không chọn đại để làm đẹp tỷ lệ.",
        "- usable_sourced_records nghĩa là đúng phạm vi kiểm tra, có bản ghi hợp schema và bằng chứng nguồn. KHÔNG xác nhận cơ sở có thật đang mở, giá/phòng trống, hoặc dữ liệu nguồn chính xác hoàn toàn.",
        "- geographic_mismatch: tọa độ mà hệ thống tự nhận nằm ngoài tỉnh tham chiếu dự kiến; phải xem lại phân giải địa danh.",
        "- Chỉ đánh giá theo ranh giới tham chiếu có phiên bản, có thể có sai số; không xác nhận pháp lý địa giới.",
        "- Dữ liệu POI thiếu không chứng minh ngoài thực tế không có địa điểm; không có cam kết bao phủ mọi POI Việt Nam.",
        f"- Giới hạn: tối đa 60 request Photon, 45 request geocoding; giãn 2,5 giây; dừng nếu 403/429. Dừng do: {transport.stop_reason or 'không'}.",
        "",
        "## Tổng hợp",
        "",
        "| Kết quả | Số ca |",
        "|---|---:|",
    ]
    lines += [f"| {key} | {value} |" for key, value in sorted(counts.items())]
    lines += [
        f"| Chưa chạy | {payload['not_run']} |",
        "",
        "## Chi tiết dữ liệu thật",
        "",
        "| STT | Tỉnh tham chiếu | Điểm thử | Loại | Kết quả | Bản ghi | Giây |",
        "|---:|---|---|---|---|---:|---:|",
    ]
    lines += [
        f"| {r['number']} | {r['province']} | {r['destination']} | {r['category']} | {r['outcome']} | {r['records']} | {r['elapsed_s']} |"
        for r in cases
    ]
    lines += [
        "",
        "## Bằng chứng",
        "",
        "- api/: phản hồi ban đầu và cuối của từng lượt, có URL và thời điểm lấy nguồn.",
        "- network/: nội dung HTTP thực nhận; network-log.json ghi URL, status, SHA-256, số byte và thời gian.",
        "- results.json và cases.csv: kết quả máy đọc được, giữ cả ca lỗi/không phân giải được.",
        "- Kiểm tra danh mục có dấu/không dấu, ID được chọn và geometry được thực hiện riêng; không dùng nguồn giả làm live.",
        "",
        "Nguồn công cộng có giới hạn sử dụng: [Photon demo policy](https://github.com/komoot/photon#demo-server). Muốn kiểm thử quét diện rộng/lặp lại cần endpoint riêng hoặc có quota phù hợp.",
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main():
    output = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / ("coverage-audit-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    )
    output.mkdir(parents=True, exist_ok=False)
    for folder in ["network", "api"]:
        (output / folder).mkdir()
    transport = AuditTransport(output)
    source = GeoPlaceService(PublicGeoClient(transport=transport, interval=2.5))
    app = create_app(
        LivePlaceSettings(travelmate_api_token="", live_place_mode="tool_workflow"),
        LivePlaceAgent(geo_service=source),
    )
    catalog_results, cases = [], []
    print("OUTPUT=" + str(output), flush=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
        timeout=150,
    ) as client:
        for region in load_catalog().regions.values():
            response = await client.post(
                "/api/v1/places/live", json=dict(destination=region["name"], search_scope="area")
            )
            data = response.json()
            okay = (
                response.status_code == 200
                and data.get("status") == "needs_location"
                and region["id"] in {p["id"] for p in data.get("location_options", [])}
            )
            catalog_results.append(
                dict(id=region["id"], name=region["name"], historical=region["historical"], passed=okay)
            )
        assert not transport.logs, "Local catalog audit must not trigger external traffic"
        print(
            f"CATALOG={sum(r['passed'] for r in catalog_results)}/{len(catalog_results)}; live starting",
            flush=True,
        )
        for index, case in enumerate(CASES):
            if transport.stop_reason:
                break
            try:
                result = await audit_case(client, case, index, output)
            except Exception as exc:
                result = dict(
                    number=index + 1,
                    province=case[0],
                    destination=case[1],
                    category=["hotel", "restaurant", "attraction"][index % 3],
                    outcome="audit_exception",
                    error_type=type(exc).__name__,
                    records=0,
                    elapsed_s=0,
                )
            cases.append(result)
            write_report(output, catalog_results, cases, transport)
            print(
                json.dumps(
                    {
                        k: result.get(k)
                        for k in ["number", "province", "destination", "outcome", "records", "elapsed_s"]
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    write_report(output, catalog_results, cases, transport)
    print("SUMMARY=" + json.dumps(Counter(r["outcome"] for r in cases), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
