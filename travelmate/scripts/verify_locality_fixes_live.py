"""Targeted real HTTP regression, explicit observed identities, no synthetic POIs.

Selection is part of each declared test scenario, not an automatic production
fallback. Empty POI results fail availability even if error handling is correct.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.geo_places import GeoPlaceService, PublicGeoClient
from app.live_place_agent import LivePlaceAgent
from app.live_place_api import LivePlaceSettings, create_app
from scripts.audit_place_coverage import AuditTransport, source_errors

SCENARIOS = [
    ("Tam Đảo", "photon:node/369491674", "Thị trấn du lịch, không phải điểm hành chính Hợp Châu"),
    ("Vườn quốc gia Cúc Phương", "photon:relation/15882261", "Tâm khu bảo tồn, không phải cửa vào"),
    ("Đà Lạt", "geonames:1584071", "Thành phố Đà Lạt, tên nguồn dùng ký tự Ð"),
    ("Bà Nà Hills", "photon:way/359114064", "Sun World Bà Nà Hills"),
    ("Fansipan", "photon:node/3989371457", "Trạm cáp treo trên núi, không đồng nhất với đỉnh núi"),
]


async def main(args):
    output = Path("evaluation") / ("fix-verification-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    (output / "network").mkdir(parents=True)
    (output / "api").mkdir()
    transport = AuditTransport(output)
    source = GeoPlaceService(PublicGeoClient(transport=transport, interval=2.5))
    app = create_app(LivePlaceSettings(travelmate_api_token=""), LivePlaceAgent(geo_service=source))
    results = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for destination, identity, intent in SCENARIOS:
            if args.destination and destination != args.destination:
                continue
            for category in ["hotel", "restaurant", "attraction"]:
                if args.category and category != args.category:
                    continue
                query = dict(
                    destination=destination,
                    location_id=identity,
                    search_scope="nearby",
                    radius_m=args.radius,
                    category=category,
                    limit=5,
                )
                response = await client.post("/api/v1/places/live", json=query)
                data = response.json()
                errors = source_errors(data, args.radius)
                selected = data.get("resolved_location") or {}
                passed = (
                    response.status_code == 200
                    and data.get("status") in {"success", "partial"}
                    and bool(data.get("places"))
                    and selected.get("id") == identity
                    and not errors
                )
                result = dict(
                    destination=destination,
                    category=category,
                    intent=intent,
                    radius_m=args.radius,
                    passed=passed,
                    status=data.get("status"),
                    records=len(data.get("places", [])),
                    errors=errors,
                )
                results.append(result)
                (output / "api" / f"{len(results):02d}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps(result, ensure_ascii=True), flush=True)
                (output / "results.json").write_text(
                    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (output / "network-log.json").write_text(
                    json.dumps(transport.logs, indent=2), encoding="utf-8"
                )
                if transport.stop_reason:
                    break
            if transport.stop_reason:
                break
    print(f"PASS={sum(r['passed'] for r in results)}/{len(results)} OUTPUT={output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", choices=[s[0] for s in SCENARIOS])
    parser.add_argument("--category", choices=["hotel", "restaurant", "attraction"])
    parser.add_argument("--radius", type=int, choices=[1000, 3000, 5000, 10000], default=5000)
    asyncio.run(main(parser.parse_args()))
