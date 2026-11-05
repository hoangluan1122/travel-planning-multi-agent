"""Call the TravelMate MCP server the way a desktop client does: launch it over stdio.

    uv run python scripts/mcp_client.py

Lists the tools and the ticket resource, then calls search_places, weather_forecast and
ask_guide for Huế. Uses the same .env as the API (live mode needs GOOGLE_API_KEY).
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def main():
    server = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(ROOT))
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        info = await session.initialize()
        print(f"Server: {info.serverInfo.name}")
        tools = await session.list_tools()
        print("Tools:", ", ".join(t.name for t in tools.tools))
        resources = await session.list_resources()
        print("Resources:", ", ".join(str(r.uri) for r in resources.resources))
        calls = [
            ("search_places", {"destination": "Huế", "category": "attraction", "limit": 4}),
            ("weather_forecast", {"destination": "Huế"}),
            ("ask_guide", {"question": "Lăng Tự Đức có gì đặc biệt, giá vé bao nhiêu?", "destination": "Huế"}),
        ]
        for name, arguments in calls:
            result = await session.call_tool(name, arguments)
            data = result.structuredContent or json.loads(result.content[0].text) if not result.isError else None
            print(f"\n{name}({json.dumps(arguments, ensure_ascii=False)}) error={result.isError}")
            print(json.dumps(data, ensure_ascii=False)[:600] if data else result.content[0].text[:300])


if __name__ == "__main__":
    asyncio.run(main())
