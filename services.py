from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.ext import Application, ContextTypes

import config
import db
from airtable_client import update_domain as airtable_update
from checker import check_domain

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "0 сек"
    if seconds < 60:
        return f"{seconds} сек"
    if seconds < 3600:
        return f"{seconds // 60} мин {seconds % 60} сек"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h} ч {m} мин"


async def notify(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, text=text, parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Telegram notification failed: %s", exc)


# ── Domain rotation ──────────────────────────────────────────────────────────

async def rotate_domain(bot: Bot, reason: str = "") -> bool:
    cooldown = int(await db.get_config("cooldown_checks", str(config.COOLDOWN_CHECKS)))
    current = await db.get_current_domain()
    current_id = current["id"] if current else None

    next_d = await db.get_next_available(cooldown, current_id)
    if next_d is None:
        await notify(
            bot,
            "🚨 <b>КРИТИЧНО: НЕТ ДОСТУПНЫХ ДОМЕНОВ</b>\n"
            "Все домены недоступны или на кулдауне!\n"
            "Требуется ручное вмешательство.",
        )
        return False

    try:
        count = await airtable_update(
            config.AIRTABLE_API_KEY,
            config.AIRTABLE_BASE_ID,
            config.AIRTABLE_TABLE_ID,
            config.AIRTABLE_VIEW_NAME,
            config.AIRTABLE_FIELD_NAME,
            next_d["domain"],
        )
    except Exception as exc:
        log.error("Airtable update failed: %s", exc)
        await notify(bot, f"❌ <b>Ошибка обновления Airtable:</b>\n<code>{exc}</code>")
        return False

    await db.set_current_domain(next_d["id"])

    if current:
        await db.add_event(current_id, "rotation_out", f"→ {next_d['domain']}, {reason}")
    await db.add_event(next_d["id"], "rotation_in", reason)

    old_name = current["domain"] if current else "—"
    await notify(
        bot,
        f"🔄 <b>ДОМЕН ЗАМЕНЁН</b>\n"
        f"Старый: <code>{old_name}</code>\n"
        f"Новый: <code>{next_d['domain']}</code>\n"
        f"Причина: {reason}\n"
        f"Airtable: обновлено ✅ ({count} зап.)",
    )
    return True


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
                    f"🟢 <b>ДОМЕН ВОССТАНОВЛЕН</b>\n"
                    f"Домен: <code>{d['domain']}</code>\n"
                    f"Даунтайм: {fmt_duration(downtime)}\n"
                    f"Статус: кулдаун (1/{cooldown} проверок до готовности)",
                )
            else:
                await db.increment_ok(d["id"])
        else:
            if was is not False:
                await db.record_down(d["id"])
                await db.add_event(d["id"], "down", "")
                await notify(
                    bot,
                    f"🔴 <b>ДОМЕН УПАЛ</b>\n"
                    f"Домен: <code>{d['domain']}</code>\n"
                    f"Попытки: {config.CHECK_RETRIES}/{config.CHECK_RETRIES} неудачно",
                )

    # If current domain is down — rotate immediately
    current = await db.get_current_domain()
    if current and not current["is_healthy"]:
        await rotate_domain(bot, reason="падение текущего домена")
    elif current is None:
        # No current domain set yet — try to assign one
        first = await db.get_next_available(cooldown)
        if first:
            await rotate_domain(bot, reason="первоначальная установка")


# ── Job callbacks (for python-telegram-bot JobQueue) ──────────────────────────

async def health_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await run_health_check(context.bot)
    except Exception:
        log.exception("Health check cycle error")


async def rotation_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await rotate_domain(context.bot, reason="плановая ротация")
    except Exception:
        log.exception("Rotation job error")


async def reschedule_rotation(app: Application, interval: int) -> None:
    for job in app.job_queue.get_jobs_by_name("rotation"):
        job.schedule_removal()
    app.job_queue.run_repeating(
        rotation_job, interval=interval, first=interval, name="rotation",
    )
