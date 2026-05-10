"""Starts aiogram long-polling as an asyncio task."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from infrastructure.telegram.handlers import router
from settings import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_polling_task: asyncio.Task | None = None


async def start_polling() -> None:
    global _bot, _polling_task

    _bot = Bot(
        token=settings.telegram.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info('Starting Telegram long-polling …')
    _polling_task = asyncio.create_task(
        dp.start_polling(_bot, allowed_updates=['message', 'callback_query'], skip_updates=False),
        name='telegram-polling',
    )


async def stop_polling() -> None:
    global _bot, _polling_task
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except (asyncio.CancelledError, RuntimeError):
            pass
    if _bot:
        await _bot.session.close()
    logger.info('Telegram polling stopped')
