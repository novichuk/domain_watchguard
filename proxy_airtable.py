from __future__ import annotations

import logging
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger(__name__)

_BASE = "https://api.airtable.com/v0"


def parse_proxy_name(name: str) -> dict | None:
    """Parse the Airtable Name field into proxy components.

    Supported formats:
      - http://user:pass@ip:port
      - socks5://user:pass@ip:port
      - ip:port:user:pass  (assumed http)
    """
    name = name.strip()
    if not name:
        return None

    if "://" in name:
        parsed = urlparse(name)
        proxy_type = "socks5" if parsed.scheme.startswith("socks") else "http"
        ip = parsed.hostname
        port = parsed.port
        username = parsed.username or ""
        password = parsed.password or ""
        if not ip or not port:
            log.warning("Cannot parse proxy URL: %s", name)
            return None
        return dict(type=proxy_type, ip=ip, port=port,
                    username=username, password=password)

    parts = name.split(":")
    if len(parts) == 4:
        ip, port_s, username, password = parts
        try:
            port = int(port_s)
        except ValueError:
            log.warning("Cannot parse proxy (bad port): %s", name)
            return None
        return dict(type="http", ip=ip, port=port,
                    username=username, password=password)

    log.warning("Unrecognised proxy name format: %s", name)
    return None


async def fetch_proxies(
    api_key: str,
    base_id: str,
    table_id: str,
    view_name: str,
) -> list[dict]:
    """Fetch all proxy records from Airtable, resolving linked names."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{_BASE}/{base_id}/{table_id}"
    params_base: dict[str, str] = {
        "view": view_name,
        "pageSize": "100",
        "cellFormat": "string",
        "timeZone": "UTC",
        "userLocale": "en",
    }

    results: list[dict] = []
    offset: str | None = None

    async with aiohttp.ClientSession(headers=headers) as session:
        while True:
            params = dict(params_base)
            if offset:
                params["offset"] = offset

            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()

            for rec in data.get("records", []):
                fields = rec.get("fields", {})
                name = fields.get("Name", "")
                parsed = parse_proxy_name(name)
                if parsed is None:
                    continue

                expire_days_raw = fields.get("Expire Days", "")
                try:
                    expire_days = int(expire_days_raw) if expire_days_raw else None
                except (ValueError, TypeError):
                    expire_days = None

                results.append(dict(
                    airtable_id=rec["id"],
                    raw_name=name,
                    **parsed,
                    esp=fields.get("ESP", ""),
                    esp_status=fields.get("ESP Status", ""),
                    expire=fields.get("Expire", ""),
                    expire_days=expire_days,
                    provider=fields.get("Proxy Providers", ""),
                    auto_renew=fields.get("Auto-Renew", ""),
                    purpose=fields.get("Purpose", ""),
                ))

            offset = data.get("offset")
            if not offset:
                break

    log.info("Fetched %d proxies from Airtable", len(results))
    return results
