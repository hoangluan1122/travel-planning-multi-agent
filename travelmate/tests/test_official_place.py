from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.agents import AgentError
from app.models import Context
from app.official_place import OfficialPlaceRequest, OfficialPlaceTool, parse_contact

HTML = """<h2 class="extended-menu-title">Changed hotel name</h2>
<div class="address">Different street<br> SAPA</div>
<div class="contact"><strong>Số điện thoại:</strong> (+84)123456789<br>Fax: 000</div>"""


def test_values_come_from_document_not_seed():
    result = parse_contact(HTML, datetime.now(UTC), "digest")
    assert result.name == "Changed hotel name"
    assert result.address == "Different street SAPA"
    assert result.telephone == "(+84)123456789"
    assert result.price_vnd is None and result.latitude is None


def test_unknown_source_and_layout_rejected():
    with pytest.raises(ValidationError):
        OfficialPlaceRequest(source_id="http://localhost")
    with pytest.raises(AgentError):
        parse_contact("<h1>Captcha</h1>", datetime.now(UTC), "digest")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 302, 403, 429, 503])
async def test_live_http_contract_no_silent_fallback(status):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(status, text=HTML, headers={"content-type": "text/html"})

    tool = OfficialPlaceTool(transport=httpx.MockTransport(handler))
    if status == 200:
        result = await tool.run(OfficialPlaceRequest(source_id="coupole-sapa"), Context(), 5)
        assert result.name == "Changed hotel name"
        assert len(result.content_sha256) == 64
    else:
        with pytest.raises(AgentError):
            await tool.run(OfficialPlaceRequest(source_id="coupole-sapa"), Context(), 5)


@pytest.mark.asyncio
async def test_robots_denial_prevents_fetch():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    with pytest.raises(AgentError):
        await OfficialPlaceTool(transport=httpx.MockTransport(handler)).run(
            OfficialPlaceRequest(source_id="coupole-sapa"),
            Context(),
            5,
        )
    assert len(calls) == 1
