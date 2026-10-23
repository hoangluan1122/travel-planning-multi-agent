"""Versioned reference regions and pure-Python point-in-polygon filtering."""

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .osm_places import normalized


def name_key(value):
    text = normalized(value).replace("_", " ")
    text = re.sub(r"^(tinh|thanh pho|tp\.?|province|city)\s+", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def in_ring(lon, lat, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        cross = (lon - ax) * (by - ay) - (lat - ay) * (bx - ax)
        if (
            abs(cross) < 1e-10
            and min(ax, bx) - 1e-10 <= lon <= max(ax, bx) + 1e-10
            and min(ay, by) - 1e-10 <= lat <= max(ay, by) + 1e-10
        ):
            return True
        if (ay > lat) != (by > lat) and lon < (bx - ax) * (lat - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def polygon_contains(geometry, lon, lat):
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return any(
        in_ring(lon, lat, polygon[0]) and not any(in_ring(lon, lat, hole) for hole in polygon[1:])
        for polygon in polygons
    )


@lru_cache(maxsize=1)
def load_catalog():
    return RegionCatalog(
        json.loads((Path(__file__).parent / "data" / "vietnam_regions.json").read_text(encoding="utf-8"))
    )


class RegionCatalog:
    def __init__(self, payload):
        self.acquired_at = datetime.fromisoformat(payload["acquired_at"])
        self.regions = {r["id"]: r for r in payload["regions"]}
        self.current = [r for r in self.regions.values() if not r["historical"]]
        assert len(self.current) == 34

    def matches(self, query):
        # Province names are exact aliases, never fuzzy matches to unrelated villages.
        key = name_key(query)
        aliases = {"hcm": "hochiminh", "tphcm": "hochiminh", "saigon": "hochiminh", "hue": "hue"}
        key = aliases.get(key, key)
        matches = []
        for region in self.regions.values():
            names = [region["name"], region["label"], *region["aliases"]]
            if key in {name_key(n) for n in names}:
                matches.append(region)
        return sorted(matches, key=lambda r: (r["historical"], r["name"]))

    def contains(self, identity, lon, lat):
        regions = self.current if identity == "vn:country" else [self.regions[identity]]
        for region in regions:
            x0, y0, x1, y1 = region["bbox"]
            if x0 <= lon <= x1 and y0 <= lat <= y1 and polygon_contains(region["geometry"], lon, lat):
                return True
        return False

    def country(self):
        boxes = [r["bbox"] for r in self.current]
        box = [
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        ]
        return dict(
            id="vn:country",
            name="Việt Nam",
            label="Việt Nam (phạm vi cả nước)",
            center=[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2],
            bbox=box,
            version="2026-03-11",
            historical=False,
            source_url=self.current[0]["source_url"],
            attribution=self.current[0]["attribution"],
        )
