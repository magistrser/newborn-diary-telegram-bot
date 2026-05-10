"""Starts aiogram long-polling and the action retry queue as asyncio tasks."""
import asyncio
import logging

import asyncpg  # type: ignore[import-untyped]
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from application.services.action_retry_queue import (
    ActionRetryQueue,
    set_retry_queue,
)
from infrastructure.repositories.fsm_state_storage import SqlFsmStorage
from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository
from infrastructure.telegram.handlers import router
from settings import PostgresSettings, settings

logger = logging.getLogger(__name__)


async def _ensure_database_exists(pg: PostgresSettings) -> None:
    conn = await asyncpg.connect(
        host=pg.host, port=pg.port,
        user=pg.user, password=pg.password,
        database='postgres',
    )
    try:
        exists = await conn.fetchval('SELECT 1 FROM pg_database WHERE datname = $1', pg.db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{pg.db_name}"')
            logger.info('Created database %r', pg.db_name)
    finally:
        await conn.close()


class _RunnerState:
    bot: Bot | None = None
    polling_task: asyncio.Task | None = None
    engine: AsyncEngine | None = None
    retry_queue: ActionRetryQueue | None = None


_state = _RunnerState()


async def start_polling() -> None:
    await _ensure_database_exists(settings.postgres)
    _state.engine = settings.postgres.create_engine()
    session_factory = async_sessionmaker(_state.engine, expire_on_commit=False)

    repo = SqlPendingActionsRepository(_state.engine, session_factory)
    _state.retry_queue = ActionRetryQueue(
        repo=repo,
        diary_api_settings=settings.diary_api,
        retry_interval_min=settings.retry.interval_min,
    )
    await _state.retry_queue.initialize()
    _state.retry_queue.start()
    set_retry_queue(_state.retry_queue)

    _state.bot = Bot(
        token=settings.telegram.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=SqlFsmStorage(_state.engine, session_factory))
    dp.include_router(router)

    logger.info('Starting Telegram long-polling …')
    _state.polling_task = asyncio.create_task(
        dp.start_polling(
            _state.bot,
            allowed_updates=['message', 'callback_query'],
            skip_updates=False,
            handle_signals=False,  # uvicorn owns signal handling; aiogram must not fight it
        ),
        name='telegram-polling',
    )


async def stop_polling() -> None:
    if _state.retry_queue:
        _state.retry_queue.stop()
    if _state.bot:
        # Close the HTTP session first so the active long-poll request to Telegram
        # is aborted immediately; otherwise aiogram's own finally-block close hangs.
        await _state.bot.session.close()
    if _state.polling_task:
        _state.polling_task.cancel()
        # asyncio.wait_for in Python 3.12+ waits for the cancelled task's finally
        # blocks before raising TimeoutError, so it can hang if aiogram's cleanup
        # makes slow network calls. asyncio.wait returns after the timeout without
        # waiting for pending tasks to finish.
        await asyncio.wait({_state.polling_task}, timeout=5.0)
    if _state.engine:
        await _state.engine.dispose()
    logger.info('Telegram polling stopped')
