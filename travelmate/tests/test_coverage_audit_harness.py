"""The recorder must not introduce source failures or bypass request budgets."""

import gzip
import hashlib
import json

import httpx
import pytest

from scripts.audit_place_coverage import AuditTransport


class RawBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


@pytest.mark.asyncio
async def test_audit_preserves_gzip_wire_body_and_client_decodes_once(monkeypatch, tmp_path):
    payload = {"type": "FeatureCollection", "features": []}
    wire = gzip.compress(json.dumps(payload).encode())

    class Network:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def handle_async_request(self, request):
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, stream=RawBody(wire), request=request
            )

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: Network())
    (tmp_path / "network").mkdir()
    audit = AuditTransport(tmp_path)
    async with httpx.AsyncClient(transport=audit) as client:
        response = await client.get("https://photon.komoot.io/api/")
        assert response.json() == payload
    assert (tmp_path / "network" / "001.bin").read_bytes() == wire
    assert audit.logs[0]["sha256"] == hashlib.sha256(wire).hexdigest()
    assert "error_type" not in audit.logs[0]


@pytest.mark.asyncio
async def test_audit_budget_cannot_be_exceeded(tmp_path):
    audit = AuditTransport(tmp_path)
    audit.counts["photon.komoot.io"] = 60
    async with httpx.AsyncClient(transport=audit) as client:
        with pytest.raises(httpx.RequestError):
            await client.get("https://photon.komoot.io/api/")
    assert audit.stop_reason == "request_budget:photon.komoot.io:60"
    assert audit.counts["photon.komoot.io"] == 60 and not audit.logs
