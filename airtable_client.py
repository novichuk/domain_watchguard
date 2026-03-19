from __future__ import annotations

import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)

_BATCH_SIZE = 10
_BASE = "https://api.airtable.com/v0"


async def update_domain(
    api_key: str,
    base_id: str,
    table_id: str,
    view_name: str,
    field_name: str,
    domain: str,
) -> int:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{_BASE}/{base_id}/{table_id}"

    async with aiohttp.ClientSession(headers=headers) as session:
        record_ids = await _fetch_all_ids(session, url, view_name, field_name)
        if not record_ids:
            return 0

        batches = [
            record_ids[i : i + _BATCH_SIZE]
            for i in range(0, len(record_ids), _BATCH_SIZE)
        ]

        log.info("Airtable: updating %d records in %d batches", len(record_ids), len(batches))

        sem = asyncio.Semaphore(5)

        async def limited(batch):
            async with sem:
                await _patch_batch(session, url, field_name, domain, batch)
                await asyncio.sleep(0.22)

        await asyncio.gather(*(limited(b) for b in batches))

    return len(record_ids)


async def _fetch_all_ids(
    session: aiohttp.ClientSession,
    url: str,
    view_name: str,
    field_name: str,
) -> list[str]:
    ids: list[str] = []
    offset: str | None = None

    while True:
        params: dict[str, str] = {
            "view": view_name,
            "pageSize": "100",
            "fields[]": field_name,
        }
        if offset:
            params["offset"] = offset

        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        for rec in data.get("records", []):
            ids.append(rec["id"])

        offset = data.get("offset")
        if not offset:
            break

    return ids


async def _patch_batch(
    session: aiohttp.ClientSession,
    url: str,
    field_name: str,
    domain: str,
    batch: list[str],
    retries: int = 3,
) -> None:
    payload = {
        "records": [
            {"id": rid, "fields": {field_name: domain}} for rid in batch
        ]
    }
    for attempt in range(retries):
        async with session.patch(url, json=payload) as resp:
            if resp.status == 200:
                return
            if resp.status == 429:
                wait = float(resp.headers.get("Retry-After", "2"))
                log.debug("Airtable 429, retry after %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            text = await resp.text()
            raise RuntimeError(f"Airtable PATCH {resp.status}: {text}")
    raise RuntimeError("Airtable: max retries exceeded")
