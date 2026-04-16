from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp_socks import ProxyConnector

log = logging.getLogger(__name__)

_TEST_URL = "http://httpbin.org/ip"


async def check_proxy(
    proxy_type: str,
    ip: str,
    port: int,
    username: str = "",
    password: str = "",
    timeout: int = 15,
    retries: int = 3,
) -> bool:
    """Connect through the proxy to httpbin.org/ip and verify we get a response."""
    for attempt in range(1, retries + 1):
        try:
            if proxy_type == "socks5":
                connector = ProxyConnector.from_url(
                    f"socks5://{username}:{password}@{ip}:{port}"
                    if username else f"socks5://{ip}:{port}"
                )
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(
                        _TEST_URL,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as resp:
                        if resp.status == 200:
                            return True
                        log.debug("%s:%d attempt %d — HTTP %d", ip, port, attempt, resp.status)
            else:
                proxy_url = (
                    f"http://{username}:{password}@{ip}:{port}"
                    if username else f"http://{ip}:{port}"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        _TEST_URL,
                        proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as resp:
                        if resp.status == 200:
                            return True
                        log.debug("%s:%d attempt %d — HTTP %d", ip, port, attempt, resp.status)
        except Exception as exc:
            log.debug("%s:%d attempt %d — %s", ip, port, attempt, exc)

        if attempt < retries:
            await asyncio.sleep(2)

    return False
