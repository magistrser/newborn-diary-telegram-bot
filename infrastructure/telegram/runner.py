"""Starts aiogram long-polling and the action retry queue as asyncio tasks."""
import asyncio
import logging
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from application.services.action_retry_queue import ActionRetryQueue, set_retry_queue
from domain.pending_action import PendingAction
from infrastructure.composition import TelegramAdapterApplicationFactory
from infrastructure.repositories.fsm_state_storage import SqlFsmStorage
from infrastructure.telegram.handlers import notify_retry_success, router
from settings import PostgresSettings, settings

logger = logging.getLogger(__name__)
_POLLING_RESTART_DELAY_SEC = 5.0


async def _ensure_database_exists(pg: PostgresSettings) -> None:
    logger.debug(
        'Checking Postgres database [host=%s port=%d database=%s user=%s]',
        pg.host, pg.port, pg.db_name, pg.user,
    )
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
        else:
            logger.debug('Postgres database exists [database=%s]', pg.db_name)
    finally:
        await conn.close()


class _RunnerState:
    bot: Bot | None = None
    polling_task: asyncio.Task[None] | None = None
    engine: AsyncEngine | None = None
    retry_queue: ActionRetryQueue | None = None
    stopping: bool = False


_state = _RunnerState()


async def _notify_retry_success(action: PendingAction, result: dict[str, Any]) -> None:
    if _state.bot is None:
        logger.warning(
            'Cannot notify Telegram retry success because bot is not connected [id=%s action_type=%s]',
            action.id, action.action_type,
        )
        return

    await notify_retry_success(_state.bot, action, result)


async def _close_bot_session(bot: Bot) -> None:
    try:
        await bot.session.close()
    except Exception:
        logger.warning('Failed to close Telegram bot HTTP session', exc_info=True)


async def _run_polling_once(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = Bot(
        token=settings.telegram.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _state.bot = bot
    bot_info = await bot.get_me()
    logger.info(
        'Connected to Telegram bot [id=%s username=@%s name=%r]',
        bot_info.id, bot_info.username, bot_info.full_name,
    )
    logger.debug(
        'Telegram routing config [allowed_chat_ids=%s allowed_authors=%s event_topic_id=%s question_topic_id=%s]',
        settings.telegram.allowed_chat_ids or 'ALL',
        settings.telegram.allowed_authors or 'ALL',
        settings.telegram.event_topic_id,
        settings.telegram.question_topic_id,
    )
    logger.debug('Telegram update logging enabled; incoming messages and callbacks will be logged before filters')
    dp = Dispatcher(storage=SqlFsmStorage(engine, session_factory))
    dp.include_router(router)

    try:
        logger.info('Starting Telegram long-polling [allowed_updates=message,callback_query]')
        await dp.start_polling(
            bot,
            allowed_updates=['message', 'callback_query'],
            skip_updates=False,
            handle_signals=False,  # uvicorn owns signal handling; aiogram must not fight it
        )
    finally:
        if _state.bot is bot:
            _state.bot = None
        await _close_bot_session(bot)
        logger.debug('Telegram bot HTTP session closed')


async def _polling_supervisor(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    restart_delay_sec: float = _POLLING_RESTART_DELAY_SEC,
) -> None:
    while not _state.stopping:
        try:
            await _run_polling_once(engine, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            if _state.stopping:
                break
            logger.exception('Telegram long-polling failed; restarting in %.1f seconds', restart_delay_sec)
        else:
            if _state.stopping:
                break
            logger.warning('Telegram long-polling stopped unexpectedly; restarting in %.1f seconds', restart_delay_sec)

        await asyncio.sleep(restart_delay_sec)


async def start_polling() -> None:
    _state.stopping = False
    logger.info('Telegram adapter runner startup started')
    await _ensure_database_exists(settings.postgres)
    engine = settings.postgres.create_engine()
    _state.engine = engine
    logger.debug('SQLAlchemy engine created [pool_size=%d]', settings.postgres.pool_size)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    _state.retry_queue = TelegramAdapterApplicationFactory.action_retry_queue(
        engine,
        session_factory,
        on_success=_notify_retry_success,
    )
    await _state.retry_queue.initialize()
    _state.retry_queue.start()
    set_retry_queue(_state.retry_queue)
    logger.debug('Action retry queue ready [pending_count=%d]', _state.retry_queue.pending_count)

    _state.polling_task = asyncio.create_task(
        _polling_supervisor(engine, session_factory),
        name='telegram-polling-supervisor',
    )
    logger.info('Telegram polling supervisor task started')


async def stop_polling() -> None:
    _state.stopping = True
    logger.info('Telegram adapter runner shutdown started')
    if _state.retry_queue:
        _state.retry_queue.stop()
    if _state.bot:
        # Close the HTTP session first so the active long-poll request to Telegram
        # is aborted immediately; otherwise aiogram's own finally-block close hangs.
        await _close_bot_session(_state.bot)
    if _state.polling_task:
        _state.polling_task.cancel()
        # asyncio.wait_for in Python 3.12+ waits for the cancelled task's finally
        # blocks before raising TimeoutError, so it can hang if aiogram's cleanup
        # makes slow network calls. asyncio.wait returns after the timeout without
        # waiting for pending tasks to finish.
        await asyncio.wait({_state.polling_task}, timeout=5.0)
        if not _state.polling_task.done():
            logger.warning('Telegram polling supervisor did not finish within shutdown timeout')
        _state.polling_task = None
    if _state.engine:
        await _state.engine.dispose()
        _state.engine = None
        logger.debug('SQLAlchemy engine disposed')
    _state.bot = None
    _state.retry_queue = None
    logger.info('Telegram polling stopped')
