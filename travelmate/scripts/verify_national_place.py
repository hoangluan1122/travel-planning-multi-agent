"""Manual, bounded acceptance checks against live sources and the local UI."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8001"
OUT = Path(__file__).resolve().parents[1] / "evaluation" / "place-national"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=BASE, timeout=140) as client:
        checks = []
        scenarios = [] if "--ui-only" in sys.argv else [
            ("Vĩnh Phúc", "hotel", True, "vinhphuc-legacy"),
            ("Đà Nẵng", "attraction", False, "danang-current"),
            ("Cà Mau", "restaurant", False, "camau-current"),
            ("Việt Nam", "hotel", None, "vietnam-country"),
        ]
        for name, category, historical, slug in scenarios:
            payload = dict(
                destination=name,
                category=category,
                limit=5,
                search_scope="country" if historical is None else "area",
            )
            r = await client.post("/api/v1/places/live", json=payload)
            r.raise_for_status()
            data = r.json()
            if data["status"] == "needs_location":
                choices = [p for p in data["location_options"] if p["historical"] is historical]
                assert len(choices) == 1, data["location_options"]
                payload["location_id"] = choices[0]["id"]
                r = await client.post("/api/v1/places/live", json=payload)
                r.raise_for_status()
                data = r.json()
            assert data["status"] in {"success", "partial"} and len(data["places"]) > 1, data["status"]
            assert data["resolved_location"]["scope"] != "nearby"
            assert all(m["spatial_filter"] == "reference_polygon" for m in data["place_metadata"].values())
            (OUT / f"{slug}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            check = dict(
                destination=name,
                category=category,
                status=data["status"],
                candidates=data["candidate_count"],
                boundary=data["resolved_location"]["boundary_version"],
                names=[p["name"] for p in data["places"]],
            )
            checks.append(check)
            print(json.dumps(check, ensure_ascii=False), flush=True)
        if checks:
            (OUT / "summary.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        await page.goto(BASE)
        await page.locator("#engine").filter(has_text="Dữ liệu thật").wait_for()
        await page.locator("#region-browser option").nth(97).wait_for(state="attached")
        assert await page.locator("#region-browser option").count() == 98
        await page.locator("#scope").select_option("area")
        assert await page.locator("#region-browser-field").is_visible()
        assert await page.locator("#radius").is_disabled()
        await page.locator("#scope").select_option("auto")
        await page.locator("#destination").fill("Vĩnh Phúc")
        async with page.expect_response(lambda r: r.url.endswith("/api/v1/places/live")) as pending:
            await page.locator("#submit").click()
        data = await (await pending.value).json()
        assert data["status"] == "needs_location" and len(data["location_options"]) == 1
        await page.locator("#location-choice option").nth(1).wait_for(state="attached")
        await page.locator("#location-choice").select_option(data["location_options"][0]["id"])
        async with page.expect_response(lambda r: r.url.endswith("/api/v1/places/live")) as pending:
            await page.locator("#submit").click()
        result = await (await pending.value).json()
        await page.locator(".place").first.wait_for()
        assert await page.locator("#radius").is_disabled()
        assert result["resolved_location"]["historical"] and await page.locator(".place").count() == 5
        await page.screenshot(path=str(OUT / "vinhphuc-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.screenshot(path=str(OUT / "vinhphuc-mobile.png"), full_page=True)
        assert not errors, errors
        print(
            "UI: explicit historical-region confirmation, sourced cards, desktop/mobile checked", flush=True
        )
        await browser.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
