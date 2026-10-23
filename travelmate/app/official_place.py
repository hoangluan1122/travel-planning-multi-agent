"""Live official-site evidence reader, not a general place search engine.

Only server-reviewed source IDs are accepted. No arbitrary URL fetching, LLM
extraction, seeded hotel facts, invented coordinates or offline fallback.
"""

import argparse
import asyncio
import hashlib
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import Field

from .agents import AgentError, BaseAgent
from .models import Context, Model

SOURCE_URL = "https://www.hoteldelacoupole.com/vi/find-us/"
USER_AGENT = "TravelMateResearch/0.1"


class OfficialPlaceRequest(Model):
    source_id: Literal["coupole-sapa"]


class OfficialPlaceEvidence(Model):
    source_id: str
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=2000)
    telephone: str | None = None
    source_url: str
    fetched_at: datetime
    content_sha256: str
    field_evidence: dict[str, str]
    latitude: float | None = None
    longitude: float | None = None
    price_vnd: float | None = None
    warnings: list[str]


class ContactParser(HTMLParser):
    """Small versioned adapter for the inspected public contact-page DOM."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = {"name": [], "address": [], "contact": []}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        key = None
        if tag == "h2" and "extended-menu-title" in classes:
            key = "name"
        elif tag == "div" and "address" in classes:
            key = "address"
        elif tag == "div" and "contact" in classes:
            key = "contact"
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, key))
        elif tag == "br":
            self.handle_data(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for key in {key for _, key in self.stack if key}:
            self.parts[key].append(data)

    def values(self):
        return {key: " ".join(" ".join(parts).split()) for key, parts in self.parts.items()}


def parse_contact(html, fetched_at, digest):
    import re

    parser = ContactParser()
    parser.feed(html)
    values = parser.values()
    if not values["name"] or "sapa" not in values["address"].casefold():
        raise AgentError("Official page layout/location could not be validated")
    phone = re.search(r"Số điện thoại:\s*([+()\d .-]+)", values["contact"])
    evidence = {key: values[key] for key in ("name", "address")}
    telephone = phone.group(1).strip() if phone else None
    if telephone:
        evidence["telephone"] = telephone
    return OfficialPlaceEvidence(
        source_id="coupole-sapa",
        name=values["name"],
        address=values["address"],
        telephone=telephone,
        source_url=SOURCE_URL,
        fetched_at=fetched_at,
        content_sha256=digest,
        field_evidence=evidence,
        warnings=[
            "Đọc trực tiếp website chính thức; địa chỉ được giữ nguyên theo nguồn.",
            "Chưa xác minh tọa độ, giá, phòng trống, giờ mở cửa hoặc quyền sử dụng ảnh.",
            "Đây là đọc chi tiết một nguồn đã cấu hình, không phải tìm kiếm toàn bộ Sa Pa.",
        ],
    )


class OfficialPlaceTool(BaseAgent[OfficialPlaceRequest, OfficialPlaceEvidence]):
    name = "official_place"
    input_schema, output_schema = OfficialPlaceRequest, OfficialPlaceEvidence

    def __init__(self, *, transport=None):
        self.transport = transport

    async def execute(self, data, context):
        # Literal source_id validation happens in BaseAgent.run. No user URL is fetched.
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=15,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            try:
                robots = await client.get("https://www.hoteldelacoupole.com/robots.txt")
                if robots.status_code != 200:
                    raise AgentError("Cannot verify source crawling policy")
                policy = RobotFileParser()
                policy.parse(robots.text.splitlines())
                if not policy.can_fetch(USER_AGENT, SOURCE_URL):
                    raise AgentError("Source disallows this reader")
                async with client.stream("GET", SOURCE_URL) as response:
                    if response.status_code != 200:
                        raise AgentError("Official source unavailable; no fallback data")
                    if "text/html" not in response.headers.get("content-type", ""):
                        raise AgentError("Expected official HTML page")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            raise AgentError("Official page exceeds size limit")
                return parse_contact(
                    body.decode("utf-8", errors="strict"),
                    datetime.now(UTC),
                    hashlib.sha256(body).hexdigest(),
                )
            except httpx.TimeoutException:
                raise TimeoutError("Official source timed out") from None
            except (httpx.HTTPError, UnicodeError):
                raise AgentError("Official source could not be read") from None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", default="coupole-sapa", choices=["coupole-sapa"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = await OfficialPlaceTool().run(
        OfficialPlaceRequest(source_id=args.source_id),
        Context(),
        40,
    )
    rendered = result.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
