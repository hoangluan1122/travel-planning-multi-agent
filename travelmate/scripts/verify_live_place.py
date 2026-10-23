"""Opt-in network/UI acceptance check; never part of the offline unit suite."""

import asyncio
import json
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parents[1] / "evaluation" / "place-v2"
BASE = "http://127.0.0.1:8001"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        for destination, category, slug in [
            ("Cát Bà", "hotel", "catba-hotels"),
            ("Cát Bà", "restaurant", "catba-restaurants"),
            ("Cát Bà", "attraction", "catba-attractions"),
            ("Sa Pa", "hotel", "sapa-hotels"),
            ("Đà Nẵng", "restaurant", "danang-restaurants"),
        ]:
            response = await client.post(
                "/api/v1/places/live",
                json={
                    "destination": destination,
                    "category": category,
                    "limit": 5,
                    "radius_m": 3000,
                    "search_scope": "nearby",
                },
            )
            response.raise_for_status()
            data = response.json()
            # Selection is explicit and checked against known administrative context.
            if data["status"] == "needs_location":
                name = "Sa Pa" if destination == "Sa Pa" else "Đà Nẵng"
                matches = [p for p in data["location_options"] if p["name"] == name]
                if len(matches) != 1:
                    print(
                        json.dumps(
                            {"destination": destination, "options": data["location_options"]},
                            ensure_ascii=False,
                        )
                    )
                    continue
                response = await client.post(
                    "/api/v1/places/live",
                    json={
                        "destination": destination,
                        "category": category,
                        "limit": 5,
                        "radius_m": 3000,
                        "search_scope": "nearby",
                        "location_id": matches[0]["id"],
                    },
                )
                response.raise_for_status()
                data = response.json()
            assert data["status"] in {"success", "partial"}, data["status"]
            assert len(data["places"]) > 1
            assert len({p["id"] for p in data["places"]}) == len(data["places"])
            for place in data["places"]:
                assert place["field_sources"]["latitude"] == place["source_url"]
                assert data["place_metadata"][place["id"]]["distance_m"] <= 3000
            (OUT / f"{slug}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    dict(
                        destination=destination,
                        category=category,
                        status=data["status"],
                        candidates=data["candidate_count"],
                        names=[p["name"] for p in data["places"]],
                    ),
                    ensure_ascii=False,
                )
            )
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE)
        await page.locator("#engine").filter(has_text="Dữ liệu thật").wait_for()
        async with page.expect_response(lambda r: r.url.endswith("/api/v1/places/live")) as pending:
            await page.locator("#submit").click()
        data = await (await pending.value).json()
        await page.locator(".place").first.wait_for()
        assert await page.locator(".place").count() == 5
        first_ids = {p["id"] for p in data["places"]}
        async with page.expect_download() as downloading:
            await page.locator("#download").click()
        download = await downloading.value
        await download.save_as(OUT / "ui-export.json")
        assert (
            json.loads((OUT / "ui-export.json").read_text(encoding="utf-8"))["request_id"]
            == data["request_id"]
        )
        await page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        async with page.expect_response(lambda r: r.url.endswith("/api/v1/places/live")) as pending:
            await page.locator("#next").click()
        next_data = await (await pending.value).json()
        assert next_data["offset"] == 5 and not first_ids & {p["id"] for p in next_data["places"]}
        await page.locator("#submit:not([disabled])").wait_for()
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert not errors, errors
        print("UI: five cards, JSON export identity, pagination, mobile overflow and JS checked")
        await browser.close()


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
