from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram import Bot
from telegram.ext import Application, ContextTypes

import config
import db
from proxy_airtable import fetch_proxies
from proxy_checker import check_proxy
from services import notify

log = logging.getLogger(__name__)

_EXPIRY_ALERT_COOLDOWN = timedelta(hours=12)


async def run_proxy_check(bot: Bot) -> None:
    """Main proxy check cycle: fetch from Airtable, check, alert."""
    try:
        proxies = await fetch_proxies(
            config.AIRTABLE_API_KEY,
            config.PROXY_AIRTABLE_BASE_ID,
            config.PROXY_AIRTABLE_TABLE_ID,
            config.PROXY_AIRTABLE_VIEW,
        )
    except Exception as exc:
        log.error("Failed to fetch proxies from Airtable: %s", exc)
        await notify(bot, f"❌ <b>Proxy Airtable fetch failed:</b>\n<code>{exc}</code>")
        return

    if not proxies:
        log.info("No proxies found in Airtable")
        return

    active_ids = {p["airtable_id"] for p in proxies}
    await db.cleanup_stale_proxies(active_ids)

    for p in proxies:
        await db.upsert_proxy(
            p["airtable_id"], p["raw_name"],
            p["ip"], p["port"], p["type"],
        )

    timeout = config.PROXY_CHECK_TIMEOUT
    retries = config.PROXY_CHECK_RETRIES
    warn_days = config.PROXY_EXPIRY_WARN_DAYS

    results = await asyncio.gather(*(
        check_proxy(p["type"], p["ip"], p["port"],
                    p["username"], p["password"], timeout, retries)
        for p in proxies
    ))

    now = datetime.now(timezone.utc)

    for p, healthy in zip(proxies, results):
        aid = p["airtable_id"]
        prev = await db.get_proxy(aid)
        was_healthy = prev["is_healthy"] if prev else None

        await db.update_proxy_health(aid, healthy)

        label = f"{p['ip']}:{p['port']}"
        usage_parts = [s for s in [
            f"ESP: {p['esp']}" if p["esp"] else "",
            f"Purpose: {p['purpose']}" if p["purpose"] else "",
        ] if s]
        usage_line = "\n" + " | ".join(usage_parts) if usage_parts else ""

        if not healthy and was_healthy is not False:
            await db.add_proxy_event(aid, "down", f"{label}")
            await notify(
                bot,
                f"🔴 <b>PROXY DOWN</b>\n"
                f"Proxy: <code>{label}</code> [{p['type'].upper()}]\n"
                f"Provider: {p['provider'] or '—'}{usage_line}\n"
                f"Retries: {retries}/{retries} failed",
            )
        elif healthy and was_healthy is False:
            await db.add_proxy_event(aid, "up", f"{label}")
            await db.clear_proxy_down(aid)
            await notify(
                bot,
                f"🟢 <b>PROXY IS UP</b>\n"
                f"Proxy: <code>{label}</code> [{p['type'].upper()}]\n"
                f"Provider: {p['provider'] or '—'}{usage_line}",
            )

        if p["expire_days"] is not None and p["expire_days"] <= warn_days:
            should_alert = True
            if prev and prev["last_expiry_alert_at"]:
                elapsed = now - prev["last_expiry_alert_at"]
                if elapsed < _EXPIRY_ALERT_COOLDOWN:
                    should_alert = False

            if should_alert:
                renew = "Yes" if p["auto_renew"] == "True" else "No"
                await db.set_expiry_alert_sent(aid)
                await db.add_proxy_event(aid, "expiry_warning",
                                         f"{p['expire_days']}d left")
                await notify(
                    bot,
                    f"⚠️ <b>PROXY EXPIRING SOON</b>\n"
                    f"Proxy: <code>{label}</code> [{p['type'].upper()}]\n"
                    f"Provider: {p['provider'] or '—'}{usage_line}\n"
                    f"Expires: {p['expire']} ({p['expire_days']}d left)\n"
                    f"Auto-renew: {renew}",
                )

    total = len(proxies)
    healthy_count = sum(1 for h in results if h)
    log.info("Proxy check done: %d/%d healthy", healthy_count, total)


async def format_proxy_status() -> str:
    """Build the status message for /list_proxies command."""
    try:
        proxies = await fetch_proxies(
            config.AIRTABLE_API_KEY,
            config.PROXY_AIRTABLE_BASE_ID,
            config.PROXY_AIRTABLE_TABLE_ID,
            config.PROXY_AIRTABLE_VIEW,
        )
    except Exception as exc:
        return f"❌ Failed to fetch proxies: {exc}"

    if not proxies:
        return "🔌 No proxies configured."

    db_proxies = {r["airtable_id"]: r for r in await db.get_all_proxies()}

    total = len(proxies)
    healthy = 0
    lines: list[str] = []

    for i, p in enumerate(proxies, 1):
        db_rec = db_proxies.get(p["airtable_id"])
        is_healthy = db_rec["is_healthy"] if db_rec else None

        if is_healthy is True:
            icon = "🟢"
            healthy += 1
        elif is_healthy is False:
            icon = "🔴"
        else:
            icon = "⚪"
            healthy += 1

        label = f"{p['ip']}:{p['port']}"
        ptype = p["type"].upper()

        esp_part = f"ESP: {p['esp']}" if p["esp"] else ""
        purpose_part = f"Purpose: {p['purpose']}" if p["purpose"] else ""
        usage = " | ".join(filter(None, [esp_part, purpose_part]))
        usage_line = f"\n   {usage}" if usage else ""

        provider = p["provider"] or "—"
        renew = "Yes" if p["auto_renew"] == "True" else "No"

        expire_str = ""
        if p["expire_days"] is not None:
            expire_str = f"{p['expire_days']}d"
            if p["expire_days"] <= config.PROXY_EXPIRY_WARN_DAYS:
                expire_str += " ⚠️"
        else:
            expire_str = p["expire"] or "—"

        esp_status = p.get("esp_status", "")
        status_tag = ""
        if is_healthy is False:
            status_tag = " [DOWN]"
        elif esp_status and esp_status != "Live":
            status_tag = f" [{esp_status}]"

        lines.append(
            f"{i}. {icon} <code>{label}</code> [{ptype}]{status_tag}{usage_line}\n"
            f"   Provider: {provider} | Auto-renew: {renew}\n"
            f"   Expires: {expire_str}"
        )

    header = f"🔌 <b>Proxy Status</b> ({total} total, {healthy} healthy):\n"
    return header + "\n\n".join(lines)


# ── Job callbacks ────────────────────────────────────────────────────────────

async def proxy_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await run_proxy_check(context.bot)
    except Exception:
        log.exception("Proxy check cycle error")


async def reschedule_proxy_check(app: Application, interval: int) -> None:
    for job in app.job_queue.get_jobs_by_name("proxy_check"):
        job.schedule_removal()
    app.job_queue.run_repeating(
        proxy_check_job, interval=interval, first=interval, name="proxy_check",
    )
