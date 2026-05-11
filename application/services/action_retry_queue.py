"""Persistent retry queue for failed diary-API action messages.

Failed ``parse_text`` and ``create_event`` calls are stored in Postgres (via
``SqlPendingActionsRepository``) so they survive adapter restarts.  A
background loop re-attempts them every *retry_interval_min* minutes until the
server accepts them.

Architecture
-----------
* ``PendingAction`` — Pydantic domain model; repo-agnostic.
* ``ActionRetryQueue`` — in-memory dict + background loop; delegates all
  persistence to an injected *repo* object that satisfies the implicit
  protocol: ``setup() / load_all() / upsert() / delete()``.
* The concrete repo lives in ``infrastructure/repositories/``.
* ``set_retry_queue`` / ``get_retry_queue`` manage the process-level singleton
  that handlers look up at call time.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from application.ports import DiaryApiPort, PendingActionsRepositoryPort
from domain.pending_action import PendingAction

logger = logging.getLogger(__name__)


# ── queue ─────────────────────────────────────────────────────────────────────

class ActionRetryQueue:
    """Keeps failed actions in memory and retries them against the diary API.

    The *repo* argument must provide:
        async def setup() -> None
        async def load_all() -> list[PendingAction]
        async def upsert(action: PendingAction) -> None
        async def delete(action_id: str) -> None
    """

    def __init__(
        self,
        repo: PendingActionsRepositoryPort,
        diary_api: DiaryApiPort,
        retry_interval_min: int = 10,
    ) -> None:
        self._repo = repo
        self._diary_api = diary_api
        self._interval_min = retry_interval_min
        self._actions: dict[str, PendingAction] = {}
        self._task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Create the DB table (if absent) and load any previously queued actions."""
        await self._repo.setup()
        actions = await self._repo.load_all()
        self._actions = {a.id: a for a in actions}
        logger.info('Loaded %d pending action(s) from database', len(self._actions))

    # ── enqueue ───────────────────────────────────────────────────────────────

    async def enqueue_parse_text(
        self,
        *,
        text: str,
        occurred_at: datetime,
        source_type: str,
        source_message_id: str | None = None,
        source_chat_id: int | None = None,
    ) -> str:
        action = PendingAction(
            action_type='parse_text',
            created_at=datetime.now(timezone.utc).isoformat(),
            text=text,
            occurred_at=occurred_at.isoformat(),
            source_type=source_type,
            source_message_id=source_message_id,
            source_chat_id=source_chat_id,
        )
        self._actions[action.id] = action
        await self._repo.upsert(action)
        logger.warning('Queued failed parse_text for retry [id=%s]', action.id)
        return action.id

    async def enqueue_create_event(
        self,
        *,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        source_type: str,
    ) -> str:
        action = PendingAction(
            action_type='create_event',
            created_at=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            occurred_at=occurred_at.isoformat(),
            payload=payload,
            source_type=source_type,
        )
        self._actions[action.id] = action
        await self._repo.upsert(action)
        logger.warning('Queued failed create_event for retry [id=%s]', action.id)
        return action.id

    # ── retry ─────────────────────────────────────────────────────────────────

    async def retry_once(self) -> tuple[int, int]:
        """Attempt every pending action once. Returns ``(succeeded, failed)``."""
        if not self._actions:
            return 0, 0

        succeeded = 0
        failed = 0

        for action_id in list(self._actions):
            action = self._actions.get(action_id)
            if action is None:
                continue
            action.attempt_count += 1
            try:
                await _execute(self._diary_api, action)
                del self._actions[action_id]
                await self._repo.delete(action_id)
                succeeded += 1
                logger.info(
                    'Retry succeeded for action %s (attempt %d)',
                    action_id, action.attempt_count,
                )
            except Exception as exc:
                await self._repo.upsert(action)   # persist updated attempt_count
                failed += 1
                logger.warning(
                    'Retry failed for action %s (attempt %d): %s',
                    action_id, action.attempt_count, exc,
                )

        return succeeded, failed

    async def _retry_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_min * 60)
            if self._actions:
                logger.info('Retrying %d pending action(s)…', len(self._actions))
                try:
                    succeeded, failed = await self.retry_once()
                except asyncio.CancelledError:
                    logger.info('Action retry loop cancelled')
                    raise
                except Exception:
                    logger.exception('Action retry loop failed; will try again on the next interval')
                else:
                    logger.info(
                        'Retry pass completed [succeeded=%d failed=%d pending=%d]',
                        succeeded, failed, self.pending_count,
                    )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._retry_loop(), name='action-retry-loop')
        logger.info('Action retry loop started (interval=%d min)', self._interval_min)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info('Action retry loop stopped')

    @property
    def pending_count(self) -> int:
        return len(self._actions)


# ── module-level singleton ────────────────────────────────────────────────────

class _QueueHolder:
    queue: ActionRetryQueue | None = None


_holder = _QueueHolder()


def set_retry_queue(queue: ActionRetryQueue) -> None:
    _holder.queue = queue


def get_retry_queue() -> ActionRetryQueue:
    if _holder.queue is None:
        raise RuntimeError('ActionRetryQueue has not been initialised — call set_retry_queue() first')
    return _holder.queue


# ── execution helper ──────────────────────────────────────────────────────────

async def _execute(client: DiaryApiPort, action: PendingAction) -> None:
    occurred_at = (
        datetime.fromisoformat(action.occurred_at)
        if action.occurred_at
        else datetime.now(timezone.utc)
    )
    if action.action_type == 'parse_text':
        await client.parse_text(
            text=action.text or '',
            occurred_at=occurred_at,
            source_type=action.source_type or 'telegram_live',
            source_message_id=action.source_message_id,
            source_chat_id=action.source_chat_id,
        )
    elif action.action_type == 'create_event':
        await client.create_event(
            event_type=action.event_type or '',
            occurred_at=occurred_at,
            payload=action.payload or {},
            source_type=action.source_type or 'telegram_quick_action',
        )
    else:
        raise ValueError(f'Unknown action_type: {action.action_type!r}')
