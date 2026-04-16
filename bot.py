from __future__ import annotations

import re
import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

import config
import db
from services import fmt_duration, rotate_domain, reschedule_rotation
from proxy_service import format_proxy_status, reschedule_proxy_check

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


def normalize_domain(raw: str) -> str | None:
    d = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.rstrip("/")
    if "." not in d or " " in d:
        return None
    return d


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛡 <b>Domain Watchguard</b>\n\n"
        "<b>Domains:</b>\n"
        "/set_domains — set domain list\n"
        "/add_domains — add domains\n"
        "/list_domains — current domain list\n"
        "/change_domain_now — rotate domain now\n"
        "/set_change_interval — set rotation interval\n\n"
        "<b>Proxies:</b>\n"
        "/list_proxies — proxy status\n"
        "/set_proxy_check_interval — set proxy check interval",
        parse_mode="HTML",
    )


async def cmd_set_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.message.text.split("\n", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Provide domains, each on a new line:\n\n"
            "/set_domains\nexample1.com\nexample2.com",
        )
        return

    raw = [d.strip() for d in parts[1].strip().split("\n") if d.strip()]
    domains = [d for d in (normalize_domain(r) for r in raw) if d]
    skipped = len(raw) - len(domains)
    if not domains:
        await update.message.reply_text("No valid domains found in the message.")
        return

    count = await db.set_domains(domains)
    msg = f"✅ {count} domains set.\nFirst check in a few seconds."
    if skipped:
        msg += f"\n⚠️ Skipped {skipped} invalid line(s)."
    await update.message.reply_text(msg)


async def cmd_add_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.message.text.split("\n", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Provide domains:\n\n/add_domains\nexample.com",
        )
        return

    domains = [d for d in (normalize_domain(r) for r in parts[1].strip().split("\n") if r.strip()) if d]
    added = await db.add_domains(domains)
    await update.message.reply_text(f"✅ Added: {added}")


async def cmd_list_domains(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    domains = await db.get_all_domains()
    if not domains:
        await update.message.reply_text("📋 Domain list is empty.")
        return

    cooldown = int(await db.get_config("cooldown_checks", str(config.COOLDOWN_CHECKS)))
    change_sec = int(await db.get_config("change_interval", str(config.CHANGE_INTERVAL)))

    lines: list[str] = [
        f"📋 <b>Domains</b> (rotation every {fmt_duration(change_sec)}):\n",
    ]

    for i, d in enumerate(domains, 1):
        if d["is_current"]:
            icon, tag = "🔵", " [ACTIVE]"
        elif d["is_healthy"] is None:
            icon, tag = "⚪", " [unchecked]"
        elif not d["is_healthy"]:
            icon, tag = "🔴", " [DOWN]"
        elif d["total_downs"] > 0 and d["consecutive_ok"] < cooldown:
            icon, tag = "🟡", f" [cooldown {d['consecutive_ok']}/{cooldown}]"
        else:
            icon, tag = "🟢", ""

        downs_30d = await db.get_downs_30d(d["id"])
        dt_sec = d["total_downtime"]
        dt_str = fmt_duration(dt_sec)

        added = d["added_at"]
        from datetime import datetime, timezone
        total_sec = int((datetime.now(timezone.utc) - added).total_seconds())
        pct = f"{dt_sec / total_sec * 100:.1f}%" if total_sec > 0 else "0%"

        lines.append(
            f"{i}. {icon} <code>{d['domain']}</code>{tag}\n"
            f"    ↓{downs_30d} (30d) | downtime: {dt_str} ({pct})",
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_change_domain_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ok = await rotate_domain(ctx.bot, reason="manual rotation")
    if not ok:
        await update.message.reply_text("❌ No available domains for rotation.")


async def cmd_set_change_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(ctx.args) if ctx.args else ""
    if not raw:
        current = await db.get_config("change_interval", str(config.CHANGE_INTERVAL))
        await update.message.reply_text(
            f"Current interval: {fmt_duration(int(current))}\n"
            f"Usage: /set_change_interval 1h",
        )
        return

    seconds = parse_interval(raw)
    if not seconds or seconds < 60:
        await update.message.reply_text(
            "❌ Invalid format. Examples: 1h, 30m, 2h, 30 min",
        )
        return

    await db.set_config("change_interval", str(seconds))
    await reschedule_rotation(ctx.application, seconds)
    await update.message.reply_text(
        f"✅ Rotation interval: {fmt_duration(seconds)}",
    )


# ── Proxy commands ────────────────────────────────────────────────────────────

async def cmd_list_proxies(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await format_proxy_status()
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_set_proxy_check_interval(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    raw = " ".join(ctx.args) if ctx.args else ""
    if not raw:
        current = await db.get_config(
            "proxy_check_interval", str(config.PROXY_CHECK_INTERVAL),
        )
        await update.message.reply_text(
            f"Current proxy check interval: {fmt_duration(int(current))}\n"
            f"Usage: /set_proxy_check_interval 10m",
        )
        return

    seconds = parse_interval(raw)
    if not seconds or seconds < 60:
        await update.message.reply_text(
            "❌ Invalid format. Examples: 10m, 30m, 1h",
        )
        return

    await db.set_config("proxy_check_interval", str(seconds))
    await reschedule_proxy_check(ctx.application, seconds)
    await update.message.reply_text(
        f"✅ Proxy check interval: {fmt_duration(seconds)}",
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
        ("list_proxies", cmd_list_proxies),
        ("set_proxy_check_interval", cmd_set_proxy_check_interval),
    ]
    for name, callback in h:
        app.add_handler(CommandHandler(name, callback, filters=_CHAT))
