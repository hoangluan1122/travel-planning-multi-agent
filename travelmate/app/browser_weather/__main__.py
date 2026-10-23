import argparse
import asyncio
import sys
from pathlib import Path

from ..models import Context
from .coccoc import open_coccoc
from .models import BrowserWeatherRequest
from .tool import BrowserWeatherTool


async def run(args):
    request = BrowserWeatherRequest.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
    tool = BrowserWeatherTool(
        lambda: open_coccoc(channel=args.channel, headless=not args.headed),
        evidence_dir=args.evidence_dir,
    )
    result = await tool.run(request, Context(), timeout=60)
    text = result.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Read Cốc Cốc weather card through an isolated browser")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--channel", choices=["msedge", "chrome", "chromium"])
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        parser.exit(1, f"Weather tool failed ({type(exc).__name__}); check configuration/input.\n")


if __name__ == "__main__":
    main()
