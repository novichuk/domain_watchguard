from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application

import config
import db
from bot import setup_handlers
from services import fmt_duration, health_check_job, notify, rotation_job
from proxy_service import proxy_check_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    await db.init(config.DB_CONFIG)

    check_interval = int(await db.get_config("check_interval", str(config.CHECK_INTERVAL)))
    change_interval = int(await db.get_config("change_interval", str(config.CHANGE_INTERVAL)))

    if not await db.get_config("cooldown_checks"):
        await db.set_config("cooldown_checks", str(config.COOLDOWN_CHECKS))

    app.job_queue.run_repeating(
        health_check_job, interval=check_interval, first=10, name="health_check",
    )
    app.job_queue.run_repeating(
        rotation_job, interval=change_interval, first=change_interval, name="rotation",
    )

    proxy_interval = int(await db.get_config(
        "proxy_check_interval", str(config.PROXY_CHECK_INTERVAL),
    ))
    app.job_queue.run_repeating(
        proxy_check_job, interval=proxy_interval, first=30, name="proxy_check",
    )

    await app.bot.set_my_commands([
        BotCommand("set_domains", "Set domain list"),
        BotCommand("add_domains", "Add domains"),
        BotCommand("list_domains", "Current domain list"),
        BotCommand("change_domain_now", "Rotate domain now"),
        BotCommand("set_change_interval", "Set rotation interval"),
        BotCommand("list_proxies", "Proxy status"),
        BotCommand("set_proxy_check_interval", "Set proxy check interval"),
    ])

    await notify(
        app.bot,
        f"🛡 <b>Domain Watchguard started</b>\n"
        f"Domain check: {fmt_duration(check_interval)}\n"
        f"Rotation: {fmt_duration(change_interval)}\n"
        f"Proxy check: {fmt_duration(proxy_interval)}",
    )

    log.info(
        "Started — domain check %ds, rotate %ds, proxy check %ds",
        check_interval, change_interval, proxy_interval,
    )


async def post_shutdown(app: Application) -> None:
    await db.close()


def main() -> None:
    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    setup_handlers(app)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
