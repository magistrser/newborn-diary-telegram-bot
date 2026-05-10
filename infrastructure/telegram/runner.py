"""Starts aiogram long-polling and the action retry queue as asyncio tasks."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from application.services.action_retry_queue import (
    ActionRetryQueue,
    set_retry_queue,
)
from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository
from infrastructure.telegram.handlers import router
from settings import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_polling_task: asyncio.Task | None = None
_engine: AsyncEngine | None = None
_retry_queue: ActionRetryQueue | None = None


async def start_polling() -> None:
    global _bot, _polling_task, _engine, _retry_queue

    _engine = settings.postgres.create_engine()
    session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    repo = SqlPendingActionsRepository(_engine, session_factory)
    _retry_queue = ActionRetryQueue(
        repo=repo,
        diary_api_settings=settings.diary_api,
        retry_interval_min=settings.retry.interval_min,
    )
    await _retry_queue.initialize()
    _retry_queue.start()
    set_retry_queue(_retry_queue)

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
    if _retry_queue:
        _retry_queue.stop()
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except (asyncio.CancelledError, RuntimeError):
            pass
    if _bot:
        await _bot.session.close()
    if _engine:
        await _engine.dispose()
    logger.info('Telegram polling stopped')
