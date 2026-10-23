"""Bounded browser source discovery; snippets are NOT verified place records."""

import argparse
import asyncio
import hashlib
import ipaddress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import Field

from .agents import AgentError, BaseAgent
from .browser_weather.coccoc import open_coccoc
from .models import Context, Model, Place, PlaceSearchRequest
from .official_place import OfficialPlaceEvidence, OfficialPlaceRequest, OfficialPlaceTool
from .structured_hotel import URL_PATTERN, StructuredHotelReader

# Inspected against rendered Cốc Cốc DOM on 2026-10-22. This excludes ad cards.
RESULT_CARD = ".default-mcnSK"
EXTRACT = """els => els.filter(e => e.querySelector('h3.title-qgBH2 a')).slice(0,10).map(e => ({
  title: e.querySelector('h3.title-qgBH2 a').innerText,
  link: e.querySelector('h3.title-qgBH2 a').href,
  snippet: e.querySelector('p.desc-CZWXT')?.innerText || ''
}))"""


class WebSource(Model):
    id: str
    title: str = Field(min_length=1, max_length=1000)
    snippet: str = Field(max_length=3000)
    url: str
    search_url: str
    fetched_at: datetime
    verification: Literal["search_result_only", "structured_source_record"] = "search_result_only"


class BrowserPlaceResult(Model):
    status: Literal["sources_found", "source_error", "blocked", "timeout"]
    query: str
    search_url: str
    fetched_at: datetime
    sources: list[WebSource] = Field(default_factory=list)
    official_details: list[OfficialPlaceEvidence] = Field(default_factory=list)
    places: list[Place] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def public_link(value):
    """Validate a display link. Unknown hosts are never fetched by this tool."""
    try:
        parts = urlsplit(value)
        _ = parts.port  # Reject malformed/out-of-range ports before resolving redirect links.
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            return None
        if len(value) > 4000 or "." not in host or host.endswith((".localhost", ".local")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


async def resolve_link(client, value):
    """Read only a search redirect header, never follow it to an arbitrary host."""
    if not public_link(value):
        return None
    parsed = urlsplit(value)
    if parsed.hostname != "coccoc.com":
        # Reject tracking/advertising subdomains too.
        if parsed.hostname.endswith(".coccoc.com"):
            return None
        return value
    if parsed.path != "/composer/goto" or parsed.scheme != "https" or parsed.port is not None:
        return None
    try:
        async with client.stream("GET", value) as response:
            target = response.headers.get("location", "")
            if response.status_code not in {301, 302, 303, 307, 308}:
                return None
            if not public_link(target) or urlsplit(target).hostname.endswith("coccoc.com"):
                return None
            return target
    except httpx.HTTPError:
        return None


class BrowserPlaceTool(BaseAgent[PlaceSearchRequest, BrowserPlaceResult]):
    name, input_schema, output_schema = "browser_places", PlaceSearchRequest, BrowserPlaceResult

    def __init__(self, browser_factory=open_coccoc, official_tool=None, transport=None, hotel_reader=None):
        self.browser_factory = browser_factory
        self.official_tool = official_tool or OfficialPlaceTool()
        self.transport = transport
        self.hotel_reader = hotel_reader or StructuredHotelReader()

    async def execute(self, data, context):
        from playwright.async_api import TimeoutError as BrowserTimeout

        category = {"hotel": "hotel", "restaurant": "restaurant", "attraction": "attraction"}[data.category]
        query = " ".join(f"{category} {data.destination} {data.keyword} official website".split())
        search_url = "https://coccoc.com/search?" + urlencode({"query": query})
        result = BrowserPlaceResult(
            status="source_error",
            query=query,
            search_url=search_url,
            fetched_at=datetime.now(UTC),
            warnings=[
                "Kết quả tìm kiếm là nguồn ứng viên, chưa xác minh địa danh hoặc loại hình.",
                "Không dùng giá/snippet làm báo giá hoặc tọa độ; chưa xác minh phòng trống hoặc ảnh.",
                "Tìm bằng tên địa danh, chưa áp dụng bộ lọc bán kính hoặc location_id.",
            ],
        )
        try:
            async with asyncio.timeout(55):
                async with self.browser_factory() as card:
                    response = await card.page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    if response and response.status in {401, 403, 429}:
                        result.status = "blocked"
                        return result
                    try:
                        await card.page.locator(RESULT_CARD + " h3.title-qgBH2").first.wait_for(
                            state="visible",
                            timeout=12000,
                        )
                    except BrowserTimeout:
                        text = (await card.page.locator("body").inner_text()).casefold()
                        if any(x in text for x in ["captcha", "verify you are human", "unusual traffic"]):
                            result.status = "blocked"
                        result.warnings.append("Không đọc được danh sách; không kết luận không có địa điểm.")
                        return result
                    rows = await card.page.locator(RESULT_CARD).evaluate_all(EXTRACT)
                    for row in rows:
                        row["search_url"] = search_url
                    # A second bounded query discovers URLs on our reviewed provider.
                    # No hotel names/IDs or coordinates are seeded into either query.
                    if data.category == "hotel" and not data.keyword:
                        scoped_url = "https://coccoc.com/search?" + urlencode(
                            {"query": f"hotel {data.destination} site:mgallery.accor.com/en/hotels/"}
                        )
                        try:
                            scoped_response = await card.page.goto(
                                scoped_url,
                                wait_until="domcontentloaded",
                                timeout=12000,
                            )
                            if scoped_response and scoped_response.status in {401, 403, 429}:
                                result.warnings.append("Tìm nguồn chính thức bị chặn; không thử vượt chặn.")
                            else:
                                await card.page.locator(RESULT_CARD + " h3.title-qgBH2").first.wait_for(
                                    state="visible",
                                    timeout=6000,
                                )
                                scoped_rows = await card.page.locator(RESULT_CARD).evaluate_all(EXTRACT)
                                for row in scoped_rows:
                                    row["search_url"] = scoped_url
                                rows = scoped_rows[:2] + rows
                        except BrowserTimeout:
                            result.warnings.append(
                                "Truy vấn nguồn chính thức hết thời gian; giữ kết quả ban đầu."
                            )
                    result.fetched_at = datetime.now(UTC)
                # Browser is closed before contacting the reviewed official-site adapter.
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=4,
                    follow_redirects=False,
                    headers={"User-Agent": "TravelMateResearch/0.1"},
                ) as client:
                    seen = set()
                    for row in rows[: min(data.limit, 5)]:
                        link = await resolve_link(client, row.get("link", ""))
                        title = row.get("title", "").strip()
                        if not link or link in seen or not title:
                            continue
                        seen.add(link)
                        result.sources.append(
                            WebSource(
                                id="web:" + hashlib.sha256(link.encode()).hexdigest()[:24],
                                title=title[:1000],
                                snippet=row.get("snippet", "")[:3000],
                                url=link,
                                search_url=row.get("search_url", search_url),
                                fetched_at=result.fetched_at,
                            )
                        )
                if result.sources:
                    result.status = "sources_found"
                else:
                    result.warnings.append("Không xác minh được URL nguồn; không trả bản ghi giả.")
                if data.category == "hotel":
                    reviewed = [s for s in result.sources if URL_PATTERN.fullmatch(s.url)]
                    for source in reviewed[:2]:
                        try:
                            place = await self.hotel_reader.read(source.url, data.destination)
                            result.places.append(place)
                        except (AgentError, TimeoutError):
                            result.warnings.append(
                                "Không xác minh được khách sạn từ website hoặc địa danh không khớp."
                            )
                    if result.places:
                        result.warnings.append(
                            "Tọa độ do website chính thức công bố; chưa kiểm chứng thực địa hoặc giá/phòng trống."
                        )
                if data.category == "hotel" and any(
                    urlsplit(s.url).hostname in {"hoteldelacoupole.com", "www.hoteldelacoupole.com"}
                    for s in result.sources
                ):
                    try:
                        detail = await self.official_tool.run(
                            OfficialPlaceRequest(source_id="coupole-sapa"),
                            context,
                            20,
                        )
                        result.official_details.append(detail)
                    except (AgentError, TimeoutError):
                        result.warnings.append("Đọc website chính thức thất bại; giữ nguồn tìm kiếm riêng.")
                return result
        except (TimeoutError, BrowserTimeout):
            result.status = "sources_found" if result.sources else "timeout"
            result.warnings.append("Đã hết thời gian; kết quả có thể chưa đầy đủ.")
            return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--category", choices=["hotel", "restaurant", "attraction"], default="hotel")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = await BrowserPlaceTool().run(
        PlaceSearchRequest(
            destination=args.destination, category=args.category, keyword=args.keyword, limit=5
        ),
        Context(),
        60,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
