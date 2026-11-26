from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.ext import ContextTypes

import config
import db
from checker import check_domain

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m"


async def notify(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, text=text, parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Telegram notification failed: %s", exc)


# ── Health check cycle ────────────────────────────────────────────────────────

async def run_health_check(bot: Bot) -> None:
    domains = await db.get_all_domains()
    if not domains:
        return

    cooldown = int(await db.get_config("cooldown_checks", str(config.COOLDOWN_CHECKS)))

    results = await asyncio.gather(
        *(check_domain(d["domain"], config.CHECK_TIMEOUT, config.CHECK_RETRIES) for d in domains)
    )

    for d, healthy in zip(domains, results):
        was = d["is_healthy"]
        await db.update_health(d["id"], healthy)

        if healthy:
            if was is False:
                downtime = await db.record_up(d["id"])
                await db.add_event(d["id"], "up", f"downtime={downtime}s")
                await notify(
                    bot,
                    f"🟢 <b>DOMAIN IS UP</b>\n"
                    f"Domain: <code>{d['domain']}</code>\n"
                    f"Downtime: {fmt_duration(downtime)}\n"
                    f"Status: cooldown (1/{cooldown} checks before ready)",
                )
            else:
                await db.increment_ok(d["id"])
        else:
            if was is not False:
                await db.record_down(d["id"])
                await db.add_event(d["id"], "down", "")
                await notify(
                    bot,
                    f"🔴 <b>DOMAIN DOWN</b>\n"
                    f"Domain: <code>{d['domain']}</code>\n"
                    f"Retries: {config.CHECK_RETRIES}/{config.CHECK_RETRIES} failed",
                )


# ── Job callbacks (for python-telegram-bot JobQueue) ──────────────────────────

async def health_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await run_health_check(context.bot)
    except Exception:
        log.exception("Health check cycle error")
