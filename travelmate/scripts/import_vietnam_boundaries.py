"""Reproducible, opt-in acquisition of reference boundaries, not POI demo data."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1] / "app" / "data"
CURRENT = "https://raw.githubusercontent.com/thanglequoc/vietnamese-provinces-database/8b78ba5118715e1fa81769286724db79346abf52/mongodb/gis/mongo_data_vn_province_gis.json"
LEGACY = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbHumanitarian/VNM/ADM1/geoBoundaries-VNM-ADM1_simplified.geojson"


def get(url):
    content = bytearray()
    with httpx.stream("GET", url, timeout=40, follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > 10_000_000:
                raise ValueError("Boundary input exceeded expected size")
    return json.loads(content), hashlib.sha256(content).hexdigest()


def main():
    current, current_sha = get(CURRENT)
    legacy, legacy_sha = get(LEGACY)
    assert len(current) == 34 and len(legacy["features"]) == 63
    regions = []
    for item in current:
        gis = item["GIS"]
        box = gis["BoundingBox"]
        regions.append(
            dict(
                id=f"vn:current:{item['Code']}",
                name=item["Name"],
                label=item["FullName"],
                version="2026-03-11",
                historical=False,
                source_url=CURRENT,
                attribution="Thang Le Quoc / vietnamese-provinces-database; GIS derived from Bando.com.vn; reference snapshot 2026-03-11",
                geometry=gis["Geometry"],
                center=gis["Center"]["coordinates"],
                bbox=[box["MinLongitude"], box["MinLatitude"], box["MaxLongitude"], box["MaxLatitude"]],
                aliases=item.get("SearchKeywords", []) + [item["NameEn"], item["FullNameEn"]],
            )
        )
    for item in legacy["features"]:
        props = item["properties"]
        geometry = item["geometry"]
        polygons = (
            geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        )
        points = [point for polygon in polygons for ring in polygon for point in ring]
        box = [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ]
        regions.append(
            dict(
                id=f"vn:legacy:{props['shapeID']}",
                name=props["shapeName"],
                label=props["shapeName"] + " (khu vực cũ, ranh giới 2020)",
                version="2020",
                historical=True,
                source_url=LEGACY,
                attribution="Government of Viet Nam / HDX, via geoBoundaries gbHumanitarian VNM ADM1; CC BY 3.0 IGO; simplified reference boundaries 2020",
                geometry=geometry,
                center=[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2],
                bbox=box,
                aliases=[],
            )
        )
    ROOT.mkdir(parents=True, exist_ok=True)
    output = ROOT / "vietnam_regions.json"
    if output.exists():
        raise FileExistsError("Review/remove existing generated snapshot explicitly before reimporting")
    payload = dict(
        acquired_at=datetime.now(UTC).isoformat(),
        sources=[dict(url=CURRENT, sha256=current_sha), dict(url=LEGACY, sha256=legacy_sha)],
        regions=regions,
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Imported {len(regions)} reference regions; {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
