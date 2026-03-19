from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application

import config
import db
from bot import setup_handlers
from services import health_check_job, rotation_job

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

    await app.bot.set_my_commands([
        BotCommand("set_domains", "Задать список доменов"),
        BotCommand("add_domains", "Добавить домены"),
        BotCommand("list_domains", "Список доменов"),
        BotCommand("change_domain_now", "Заменить домен сейчас"),
        BotCommand("set_change_interval", "Интервал смены"),
    ])

    log.info("Started — check every %ds, rotate every %ds", check_interval, change_interval)


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
