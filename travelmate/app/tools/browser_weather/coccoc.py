"""Versioned DOM adapter inspected against the live card on 2026-10-21.

Reads only rendered DOM. No hidden application state, network payload interception,
CAPTCHA bypass, personal browser profile or search-snippet forecast extraction.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

CARD = ".weather-FseBM"
LOCATION = ".weather-bMd8Q"
STAMP = ".weather-OuPb7"
DAYS = ".weather-lMW2H"
HOURS = ".list-clickable rect"
SNAPSHOT = """el => {
  const text = selector => el.querySelector(selector)?.textContent.trim() || '';
  const metrics = {};
  for (const row of el.querySelectorAll('.weather-Snfcr > div')) {
    const label = row.querySelector('.weather-oA2_v')?.textContent.trim();
    if (label) metrics[label] = row.querySelector('.weather-eOr0X')?.textContent.trim() || '';
  }
  return {
    location: text('.weather-bMd8Q'), stamp: text('.weather-OuPb7'),
    temperature: text('.weather-oX8Yw'), feels_like: text('.weather-ns6aC b'),
    description: text('.weather-yWMJE'), metrics,
    text: el.innerText.slice(0,12000),
    days: [...el.querySelectorAll('.weather-lMW2H')].map(d => ({
      label: d.querySelector('.weather-t5WcO')?.textContent.trim() || '',
      high: d.querySelector('.weather-ksMJr b')?.textContent.trim() || '',
      low: d.querySelector('.weather-ksMJr span')?.textContent.trim() || ''
    }))
  };
}"""


class CardUnavailable(Exception):
    pass


class BrowserBlocked(Exception):
    pass


class CoccocCard:
    def __init__(self, page):
        self.page = page

    async def search(self, query):
        from playwright.async_api import TimeoutError as BrowserTimeout

        response = await self.page.goto(
            "https://coccoc.com/search?" + urlencode({"query": query}),
            wait_until="domcontentloaded",
            timeout=12000,
        )
        if response and response.status in {401, 403, 429}:
            raise BrowserBlocked("Access denied by source")
        try:
            await self.page.locator(CARD).wait_for(state="visible", timeout=8000)
        except BrowserTimeout:
            text = (await self.page.locator("body").inner_text())[:12000].casefold()
            if any(
                marker in text
                for marker in [
                    "verify you are human",
                    "xác minh bạn là",
                    "captcha",
                    "unusual traffic",
                    "access denied",
                ]
            ):
                raise BrowserBlocked("Source requests verification") from None
            raise CardUnavailable("Weather card missing or layout changed") from None
        return await self.snapshot()

    async def snapshot(self):
        result = await self.page.locator(CARD).evaluate(SNAPSHOT)
        result["url"] = self.page.url
        return result

    async def select_day(self, index):
        day = self.page.locator(CARD).locator(DAYS).nth(index)
        await day.scroll_into_view_if_needed()
        await day.click(timeout=3000)
        return await self.snapshot()

    async def select_hour(self, hour):
        # Verified against the current DOM: 24 hit areas in chronological order.
        # Tool still checks the displayed timestamp after EVERY click.
        areas = self.page.locator(CARD).locator(HOURS)
        if await areas.count() != 24:
            raise CardUnavailable("Hourly interaction layout changed")
        await areas.nth(hour).click(timeout=3000)
        return await self.snapshot()

    async def screenshot(self, path: Path):
        # Move away from navigation hover targets before capturing the card.
        await self.page.mouse.move(1400, 950)
        # Leave space above the card for the site's fixed navigation/promotional UI.
        await self.page.locator(CARD).evaluate(
            "el => window.scrollTo(0, Math.max(0, window.scrollY + el.getBoundingClientRect().top - 180))"
        )
        await self.page.wait_for_timeout(200)
        await self.page.locator(CARD).screenshot(path=str(path), timeout=3000)


@asynccontextmanager
async def open_coccoc(*, channel=None, headless=True):
    from playwright.async_api import async_playwright

    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(
            channel=channel or ("msedge" if sys.platform == "win32" else "chromium"), headless=headless
        )
        try:
            context = await browser.new_context(
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                viewport={"width": 1440, "height": 1000},
                accept_downloads=False,
                service_workers="block",
            )
            page = await context.new_page()
            page.set_default_timeout(4000)

            async def guard(route):
                request = route.request
                if request.is_navigation_request() and request.frame == page.main_frame:
                    url = urlsplit(request.url)
                    if url.scheme != "https" or url.hostname != "coccoc.com" or url.path != "/search":
                        await route.abort()
                        return
                await route.continue_()

            await page.route("**/*", guard)
            yield CoccocCard(page)
        finally:
            await browser.close()
