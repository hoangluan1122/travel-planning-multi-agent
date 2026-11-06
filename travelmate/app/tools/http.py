"""Bounded retries for idempotent provider GETs only, never model calls or writes."""

import asyncio

import httpx


async def get_with_retry(client, url, *, params, attempts=3, sleep=asyncio.sleep):
    if not 1 <= attempts <= 3:
        raise ValueError("Provider attempts must be between one and three")
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, params=params)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == attempts:
                raise
        else:
            # Do not retry 4xx, including quota exhaustion (429), or malformed JSON.
            if response.status_code not in {502, 503, 504} or attempt == attempts:
                response.raise_for_status()
                return response, attempt
        await sleep(0.2 * 2 ** (attempt - 1))
    raise AssertionError("Unreachable retry state")
