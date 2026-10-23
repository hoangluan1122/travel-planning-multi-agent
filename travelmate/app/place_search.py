"""Local smoke harness for real OSM tools; no LLM key required."""

import argparse
import asyncio
import sys
from pathlib import Path

from .models import Context, PlaceSearchRequest
from .osm_places import OSMLocationTool, OSMPlaceProvider, OSMSearchTool
from .place_locations import LocationQuery


async def run(args):
    provider = OSMPlaceProvider(args.endpoint)
    if args.resolve:
        result = await OSMLocationTool(provider).run(LocationQuery(destination=args.resolve), Context(), 30)
    else:
        data = PlaceSearchRequest.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
        result = await OSMSearchTool(provider).run(data, Context(), 60)
    text = result.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--resolve")
    group.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--endpoint", default="https://overpass-api.de/api/interpreter")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        parser.exit(1, f"Place lookup failed ({type(exc).__name__}); check provider/input.\n")


if __name__ == "__main__":
    main()
