from __future__ import annotations

import re
import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

import config
import db
from services import fmt_duration, rotate_domain, reschedule_rotation

log = logging.getLogger(__name__)

_CHAT = filters.Chat(config.TELEGRAM_CHAT_ID)


# ── Utilities ─────────────────────────────────────────────────────────────────

def parse_interval(text: str) -> int | None:
    m = re.match(
        r"^(\d+)\s*(h|hr|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)$",
        text.strip().lower(),
    )
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("h"):
        return val * 3600
    if unit.startswith("m"):
        return val * 60
    return val


def normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/")


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛡 <b>Domain Watchguard</b>\n\n"
        "/set_domains — задать список доменов\n"
        "/add_domains — добавить домены\n"
        "/list_domains — текущий список\n"
        "/change_domain_now — заменить домен\n"
        "/set_change_interval — интервал ротации",
        parse_mode="HTML",
    )


async def cmd_set_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.message.text.split("\n", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Укажите домены, каждый с новой строки:\n\n"
            "/set_domains\nexample1.com\nexample2.com",
        )
        return

    domains = [normalize_domain(d) for d in parts[1].strip().split("\n") if d.strip()]
    if not domains:
        await update.message.reply_text("Не найдено доменов в сообщении.")
        return

    count = await db.set_domains(domains)
    await update.message.reply_text(
        f"✅ Задано {count} доменов.\nПервая проверка через несколько секунд.",
    )


async def cmd_add_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.message.text.split("\n", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Укажите домены:\n\n/add_domains\nexample.com",
        )
        return

    domains = [normalize_domain(d) for d in parts[1].strip().split("\n") if d.strip()]
    added = await db.add_domains(domains)
    await update.message.reply_text(f"✅ Добавлено: {added}")


async def cmd_list_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    domains = await db.get_all_domains()
    if not domains:
        await update.message.reply_text("📋 Список доменов пуст.")
        return

    cooldown = int(await db.get_config("cooldown_checks", str(config.COOLDOWN_CHECKS)))
    change_sec = int(await db.get_config("change_interval", str(config.CHANGE_INTERVAL)))

    lines: list[str] = [
        f"📋 <b>Домены</b> (ротация каждые {fmt_duration(change_sec)}):\n",
    ]

    for i, d in enumerate(domains, 1):
        if d["is_current"]:
            icon, tag = "🔵", " [В РАБОТЕ]"
        elif d["is_healthy"] is None:
            icon, tag = "⚪", " [не проверен]"
        elif not d["is_healthy"]:
            icon, tag = "🔴", " [НЕДОСТУПЕН]"
        elif d["total_downs"] > 0 and d["consecutive_ok"] < cooldown:
            icon, tag = "🟡", f" [кулдаун {d['consecutive_ok']}/{cooldown}]"
        else:
            icon, tag = "🟢", ""

        dt = fmt_duration(d["total_downtime"])
        lines.append(
            f"{i}. {icon} <code>{d['domain']}</code>{tag}\n"
            f"    ↓{d['total_downs']} ↑{d['total_ups']} | даунтайм: {dt}",
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_change_domain_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ok = await rotate_domain(ctx.bot, reason="ручная замена")
    if not ok:
        await update.message.reply_text("❌ Нет доступных доменов для замены.")


async def cmd_set_change_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(ctx.args) if ctx.args else ""
    if not raw:
        current = await db.get_config("change_interval", str(config.CHANGE_INTERVAL))
        await update.message.reply_text(
            f"Текущий интервал: {fmt_duration(int(current))}\n"
            f"Использование: /set_change_interval 1h",
        )
        return

    seconds = parse_interval(raw)
    if not seconds or seconds < 60:
        await update.message.reply_text(
            "❌ Неверный формат. Примеры: 1h, 30m, 2h, 30 min",
        )
        return

    await db.set_config("change_interval", str(seconds))
    await reschedule_rotation(ctx.application, seconds)
    await update.message.reply_text(
        f"✅ Интервал смены доменов: {fmt_duration(seconds)}",
    )


# ── Registration ──────────────────────────────────────────────────────────────

def setup_handlers(app) -> None:
    h = [
        ("start", cmd_start),
        ("help", cmd_start),
        ("set_domains", cmd_set_domains),
        ("add_domains", cmd_add_domains),
        ("list_domains", cmd_list_domains),
        ("change_domain_now", cmd_change_domain_now),
        ("set_change_interval", cmd_set_change_interval),
    ]
    for name, callback in h:
        app.add_handler(CommandHandler(name, callback, filters=_CHAT))
