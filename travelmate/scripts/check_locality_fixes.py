"""Small live resolver investigation; retain actual source bytes and choices."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.geo_places import GeoPlaceService, LocalityChoiceRequired, PublicGeoClient
from scripts.audit_place_coverage import AuditTransport


async def main():
    output = Path("evaluation") / ("locality-fixes-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    (output / "network").mkdir(parents=True)
    transport = AuditTransport(output)
    service = GeoPlaceService(PublicGeoClient(transport=transport, interval=2.5))
    results = {}
    for query in ["Tràng An", "Vườn quốc gia Cúc Phương", "Tam Đảo", "Đà Lạt", "Fansipan", "Bà Nà Hills"]:
        try:
            choices = [await service.resolve(query, search_scope="nearby")]
            status = "resolved"
        except LocalityChoiceRequired as exc:
            choices, status = exc.choices, "needs_location"
        results[query] = dict(status=status, choices=[p.model_dump(mode="json") for p in choices])
        print(json.dumps({query: results[query]}, ensure_ascii=True), flush=True)
        (output / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output / "network-log.json").write_text(json.dumps(transport.logs, indent=2), encoding="utf-8")
    print(str(output), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
