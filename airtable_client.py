from __future__ import annotations

import asyncio
import logging
from functools import partial

from pyairtable import Api

log = logging.getLogger(__name__)


def _update_sync(
    api_key: str,
    base_id: str,
    table_id: str,
    view_name: str,
    field_name: str,
    domain: str,
) -> int:
    table = Api(api_key).table(base_id, table_id)
    records = table.all(view=view_name)
    for rec in records:
        table.update(rec["id"], {field_name: domain})
    return len(records)


async def update_domain(
    api_key: str,
    base_id: str,
    table_id: str,
    view_name: str,
    field_name: str,
    domain: str,
) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(_update_sync, api_key, base_id, table_id, view_name, field_name, domain),
    )
