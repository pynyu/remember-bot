"""Точка входу бота нагадувань і нотаток."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import database as db
from config import config
from handlers import setup_routers
from scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Головне меню"),
            BotCommand(command="reminders", description="Мої нагадування"),
            BotCommand(command="notes", description="Мої нотатки"),
            BotCommand(command="subs", description="Підписки"),
            BotCommand(command="checklists", description="Чеклісти"),
            BotCommand(command="templates", description="Шаблони"),
            BotCommand(command="deadline", description="Новий дедлайн"),
            BotCommand(command="today", description="Справи на сьогодні"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="settings", description="Налаштування"),
            BotCommand(command="tz", description="Часовий пояс"),
            BotCommand(command="help", description="Довідка"),
        ]
    )


async def main() -> None:
    await db.init_db()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(setup_routers())

    await setup_scheduler(bot)
    await set_commands(bot)

    log.info("Бот запускається…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await db.close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот зупинено.")
