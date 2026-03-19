from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text()


async def init(db_config: dict) -> None:
    global _pool
    _pool = await asyncpg.create_pool(**db_config, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(_SCHEMA)
    log.info("Database ready")


async def close() -> None:
    if _pool:
        await _pool.close()


# ── Config ────────────────────────────────────────────────────────────────────

async def get_config(key: str, default: str | None = None) -> str | None:
    row = await _pool.fetchrow("SELECT value FROM app_config WHERE key = $1", key)
    return row["value"] if row else default


async def set_config(key: str, value: str) -> None:
    await _pool.execute(
        """INSERT INTO app_config (key, value, updated_at) VALUES ($1, $2, NOW())
           ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
        key, value,
    )


# ── Domains CRUD ──────────────────────────────────────────────────────────────

async def set_domains(domains: list[str]) -> int:
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM domains")
            for i, d in enumerate(domains):
                await conn.execute(
                    "INSERT INTO domains (domain, sort_order) VALUES ($1, $2)",
                    d, i,
                )
    return len(domains)


async def add_domains(domains: list[str]) -> int:
    max_ord = await _pool.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) FROM domains"
    )
    added = 0
    for i, d in enumerate(domains):
        try:
            await _pool.execute(
                "INSERT INTO domains (domain, sort_order) VALUES ($1, $2)",
                d, max_ord + 1 + i,
            )
            added += 1
        except asyncpg.UniqueViolationError:
            pass
    return added


async def get_all_domains() -> list[asyncpg.Record]:
    return await _pool.fetch(
        "SELECT * FROM domains WHERE is_active = true ORDER BY sort_order"
    )


async def get_current_domain() -> asyncpg.Record | None:
    return await _pool.fetchrow(
        "SELECT * FROM domains WHERE is_current = true AND is_active = true"
    )


async def set_current_domain(domain_id: int) -> None:
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE domains SET is_current = false WHERE is_current = true")
            await conn.execute("UPDATE domains SET is_current = true WHERE id = $1", domain_id)


# ── Health transitions ────────────────────────────────────────────────────────

async def update_health(domain_id: int, healthy: bool) -> None:
    await _pool.execute(
        "UPDATE domains SET is_healthy = $2, last_checked_at = NOW() WHERE id = $1",
        domain_id, healthy,
    )


async def increment_ok(domain_id: int) -> None:
    await _pool.execute(
        "UPDATE domains SET consecutive_ok = consecutive_ok + 1 WHERE id = $1",
        domain_id,
    )


async def record_down(domain_id: int) -> None:
    await _pool.execute(
        """UPDATE domains SET
             total_downs = total_downs + 1,
             last_down_at = NOW(),
             consecutive_ok = 0
           WHERE id = $1""",
        domain_id,
    )


async def record_up(domain_id: int) -> int:
    """Mark domain as recovered; returns downtime in seconds."""
    row = await _pool.fetchrow(
        "SELECT last_down_at FROM domains WHERE id = $1", domain_id
    )
    downtime = 0
    if row and row["last_down_at"]:
        downtime = int(
            (datetime.now(timezone.utc) - row["last_down_at"]).total_seconds()
        )
    await _pool.execute(
        """UPDATE domains SET
             total_ups = total_ups + 1,
             total_downtime = total_downtime + $2,
             consecutive_ok = 1,
             last_down_at = NULL
           WHERE id = $1""",
        domain_id, downtime,
    )
    return downtime


# ── Rotation helpers ──────────────────────────────────────────────────────────

async def get_next_available(cooldown: int, current_id: int | None = None) -> asyncpg.Record | None:
    """Round-robin: pick best available domain after current sort_order.

    Priority: 1) healthy + passed cooldown  2) healthy (any)  3) None
    """
    row = await _pick_domain(cooldown, current_id, strict=True)
    if row:
        return row
    return await _pick_domain(cooldown, current_id, strict=False)


async def _pick_domain(
    cooldown: int, current_id: int | None, *, strict: bool,
) -> asyncpg.Record | None:
    cooldown_clause = "AND (total_downs = 0 OR consecutive_ok >= $1)" if strict else ""

    if current_id is not None:
        cur = await _pool.fetchrow("SELECT sort_order FROM domains WHERE id = $1", current_id)
        if cur:
            row = await _pool.fetchrow(
                f"""SELECT * FROM domains
                    WHERE is_active AND is_healthy
                      {cooldown_clause}
                      AND id != $2 AND sort_order > $3
                    ORDER BY sort_order LIMIT 1""",
                cooldown, current_id, cur["sort_order"],
            )
            if row:
                return row
        return await _pool.fetchrow(
            f"""SELECT * FROM domains
                WHERE is_active AND is_healthy
                  {cooldown_clause}
                  AND id != $2
                ORDER BY sort_order LIMIT 1""",
            cooldown, current_id,
        )

    return await _pool.fetchrow(
        f"""SELECT * FROM domains
            WHERE is_active AND is_healthy
              {cooldown_clause}
            ORDER BY sort_order LIMIT 1""",
        cooldown,
    )


# ── Events ────────────────────────────────────────────────────────────────────

async def add_event(domain_id: int, event_type: str, details: str = "") -> None:
    await _pool.execute(
        "INSERT INTO domain_events (domain_id, event_type, details) VALUES ($1, $2, $3)",
        domain_id, event_type, details,
    )


async def get_downs_30d(domain_id: int) -> int:
    row = await _pool.fetchval(
        """SELECT COUNT(*) FROM domain_events
           WHERE domain_id = $1 AND event_type = 'down'
             AND created_at >= NOW() - INTERVAL '30 days'""",
        domain_id,
    )
    return row or 0
