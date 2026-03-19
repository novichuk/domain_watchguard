from __future__ import annotations

import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)


async def check_domain(
    domain: str,
    timeout: int = 10,
    retries: int = 3,
) -> bool:
    url = domain if domain.startswith("http") else f"https://{domain}"

    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True,
                    ssl=False,
                ) as resp:
                    if resp.status == 200:
                        return True
                    log.debug("%s attempt %d — HTTP %d", domain, attempt, resp.status)
        except Exception as exc:
            log.debug("%s attempt %d — %s", domain, attempt, exc)

        if attempt < retries:
            await asyncio.sleep(2)

    return False
