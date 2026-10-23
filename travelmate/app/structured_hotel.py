"""Reviewed MGallery JSON-LD adapter. URL must come from discovered evidence."""

import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser

import httpx

from .agents import AgentError
from .models import Place
from .osm_places import normalized

URL_PATTERN = re.compile(r"https://mgallery\.accor\.com/en/hotels/[A-Za-z0-9]{4}\.html")
UA = "TravelMateResearch/0.1"


class StructuredParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.current = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.capture = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.current = []

    def handle_data(self, text):
        if self.capture:
            self.current.append(text)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            self.documents.append("".join(self.current))
            self.capture = False


def parse_hotel(html, url, destination, fetched_at):
    if not URL_PATTERN.fullmatch(url):
        raise AgentError("Unreviewed hotel URL")
    parser = StructuredParser()
    parser.feed(html)
    candidates = []
    for document in parser.documents[:30]:
        try:
            value = json.loads(document)
        except ValueError:
            continue
        nodes = value if isinstance(value, list) else [value]
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "Hotel" and node.get("url") == url:
                candidates.append(node)
    if len(candidates) != 1:
        raise AgentError("Missing or ambiguous official Hotel identity")
    item = candidates[0]
    try:
        address = item["address"]
        locality = address["addressLocality"]
        # Exact normalized locality only; no province-wide or fuzzy inference.
        if normalized(locality).replace(" ", "") != normalized(destination).replace(" ", ""):
            raise AgentError("Hotel locality does not match requested destination")
        if normalized(address["addressCountry"]) not in {"vietnam", "viet nam", "vn"}:
            raise AgentError("Hotel is outside Vietnam scope")
        street = address["streetAddress"]
        if not isinstance(street, str) or not street.strip():
            raise ValueError("Missing street")
        geo = item["geo"]
        if isinstance(geo["latitude"], bool) or isinstance(geo["longitude"], bool):
            raise ValueError("Invalid coordinates")
        return Place(
            id="official:" + hashlib.sha256(url.encode()).hexdigest()[:24],
            name=item["name"],
            address=", ".join([street, locality, address["addressCountry"]]),
            latitude=geo["latitude"],
            longitude=geo["longitude"],
            source="official_mgallery_jsonld",
            source_url=url,
            website_url=url,
            coordinate_kind="point",
            fetched_at=fetched_at,
            types=["hotel"],
            field_sources={key: url for key in ["name", "address", "latitude", "longitude", "types"]},
        )
    except (KeyError, TypeError, ValueError):
        raise AgentError("Official Hotel has invalid fields") from None


class StructuredHotelReader:
    def __init__(self, transport=None):
        self.transport = transport

    async def read(self, url, destination):
        if not URL_PATTERN.fullmatch(url):
            raise AgentError("Unreviewed hotel URL")
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=10,
                follow_redirects=False,
                headers={"User-Agent": UA},
            ) as client:
                policy_response = await client.get("https://mgallery.accor.com/robots.txt")
                if policy_response.status_code != 200 or len(policy_response.content) > 200_000:
                    raise AgentError("Cannot verify source policy")
                policy = RobotFileParser()
                policy.parse(policy_response.text.splitlines())
                if not policy.can_fetch(UA, url):
                    raise AgentError("Source disallows requested page")
                async with client.stream("GET", url) as response:
                    if response.status_code != 200 or "text/html" not in response.headers.get(
                        "content-type", ""
                    ):
                        raise AgentError("Official hotel source unavailable")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 2_000_000:
                            raise AgentError("Hotel page exceeds size limit")
                return parse_hotel(content.decode("utf-8"), url, destination, datetime.now(UTC))
        except httpx.TimeoutException:
            raise TimeoutError("Hotel source timed out") from None
        except (httpx.HTTPError, UnicodeError):
            raise AgentError("Hotel source could not be read") from None
