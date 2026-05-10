"""Tests for ActionRetryQueue and SqlPendingActionsRepository.

ActionRetryQueue tests use an InMemoryRepo — no real DB needed.
SqlPendingActionsRepository tests mock the SQLAlchemy session factory.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.services.action_retry_queue import (
    ActionRetryQueue,
    PendingAction,
    _execute,
    get_retry_queue,
    set_retry_queue,
)
from settings import DiaryApiSettings

_API_SETTINGS = DiaryApiSettings(base_url='http://test', request_timeout_sec=10)
_NOW = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)


# ── in-memory repo for unit tests ─────────────────────────────────────────────

class InMemoryRepo:
    def __init__(self, initial: list[PendingAction] | None = None) -> None:
        self.store: dict[str, PendingAction] = {a.id: a for a in (initial or [])}

    async def setup(self) -> None:
        pass

    async def load_all(self) -> list[PendingAction]:
        return list(self.store.values())

    async def upsert(self, action: PendingAction) -> None:
        self.store[action.id] = action

    async def delete(self, action_id: str) -> None:
        self.store.pop(action_id, None)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_queue(initial: list[PendingAction] | None = None, interval_min: int = 10) -> ActionRetryQueue:
    return ActionRetryQueue(
        repo=InMemoryRepo(initial),
        diary_api_settings=_API_SETTINGS,
        retry_interval_min=interval_min,
    )


def _make_parse_text_action(**overrides) -> PendingAction:
    data = dict(
        action_type='parse_text',
        created_at=_NOW.isoformat(),
        text='Заснул',
        occurred_at=_NOW.isoformat(),
        source_type='telegram_live',
        source_message_id='42',
        source_chat_id=100,
    )
    data.update(overrides)
    return PendingAction(**data)


def _make_create_event_action(**overrides) -> PendingAction:
    data = dict(
        action_type='create_event',
        created_at=_NOW.isoformat(),
        event_type='sleep_start',
        occurred_at=_NOW.isoformat(),
        payload={},
        source_type='telegram_quick_action',
    )
    data.update(overrides)
    return PendingAction(**data)


# ── initialize ────────────────────────────────────────────────────────────────

async def test_initialize_loads_existing_actions() -> None:
    pre_loaded = [_make_parse_text_action(), _make_create_event_action()]
    repo = InMemoryRepo(pre_loaded)
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()
    assert queue.pending_count == 2


async def test_initialize_with_empty_db_is_fine() -> None:
    queue = _make_queue()
    await queue.initialize()
    assert queue.pending_count == 0


# ── enqueue_parse_text ────────────────────────────────────────────────────────

async def test_enqueue_parse_text_adds_to_in_memory_and_repo() -> None:
    repo = InMemoryRepo()
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)

    action_id = await queue.enqueue_parse_text(
        text='Поел',
        occurred_at=_NOW,
        source_type='telegram_live',
        source_message_id='7',
        source_chat_id=99,
    )

    assert queue.pending_count == 1
    assert action_id in repo.store
    stored = repo.store[action_id]
    assert stored.action_type == 'parse_text'
    assert stored.text == 'Поел'
    assert stored.source_message_id == '7'
    assert stored.source_chat_id == 99


async def test_enqueue_parse_text_persists_occurred_at_as_iso() -> None:
    repo = InMemoryRepo()
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.enqueue_parse_text(text='x', occurred_at=_NOW, source_type='telegram_live')

    action = next(iter(repo.store.values()))
    assert datetime.fromisoformat(action.occurred_at) == _NOW


# ── enqueue_create_event ──────────────────────────────────────────────────────

async def test_enqueue_create_event_adds_to_in_memory_and_repo() -> None:
    repo = InMemoryRepo()
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)

    action_id = await queue.enqueue_create_event(
        event_type='diaper',
        occurred_at=_NOW,
        payload={'kind': 'pee'},
        source_type='telegram_quick_action',
    )

    assert queue.pending_count == 1
    stored = repo.store[action_id]
    assert stored.event_type == 'diaper'
    assert stored.payload == {'kind': 'pee'}


# ── retry_once — success ──────────────────────────────────────────────────────

async def test_retry_once_removes_action_on_success() -> None:
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock()

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        succeeded, failed = await queue.retry_once()

    assert succeeded == 1
    assert failed == 0
    assert queue.pending_count == 0
    assert action.id not in repo.store


async def test_retry_once_create_event_success() -> None:
    action = _make_create_event_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.create_event = AsyncMock()

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        succeeded, failed = await queue.retry_once()

    assert succeeded == 1
    assert failed == 0
    assert queue.pending_count == 0


# ── retry_once — failure ──────────────────────────────────────────────────────

async def test_retry_once_keeps_action_on_server_error() -> None:
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock(side_effect=Exception('server down'))

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        succeeded, failed = await queue.retry_once()

    assert succeeded == 0
    assert failed == 1
    assert queue.pending_count == 1
    assert action.id in repo.store


async def test_retry_once_increments_attempt_count() -> None:
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock(side_effect=Exception('down'))

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        await queue.retry_once()
        await queue.retry_once()

    assert repo.store[action.id].attempt_count == 2


async def test_retry_once_persists_updated_attempt_count_on_failure() -> None:
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock(side_effect=Exception('down'))

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        await queue.retry_once()

    assert repo.store[action.id].attempt_count == 1


# ── retry_once — empty queue ──────────────────────────────────────────────────

async def test_retry_once_returns_zeros_when_no_actions() -> None:
    queue = _make_queue()
    succeeded, failed = await queue.retry_once()
    assert succeeded == 0
    assert failed == 0


# ── multiple actions ──────────────────────────────────────────────────────────

async def test_retry_once_handles_mixed_success_failure() -> None:
    good = _make_parse_text_action()
    bad = _make_create_event_action()
    repo = InMemoryRepo([good, bad])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue.initialize()

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock()
    mock_client.create_event = AsyncMock(side_effect=Exception('nope'))

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        succeeded, failed = await queue.retry_once()

    assert succeeded == 1
    assert failed == 1
    assert good.id not in repo.store
    assert bad.id in repo.store


# ── restart persistence ───────────────────────────────────────────────────────

async def test_restart_loads_failed_actions_and_retries() -> None:
    """Simulate an adapter restart: pre-populate the repo, create a new queue,
    initialise it, verify it picks up the pending action and retries it."""
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])  # shared repo simulates the persistent DB

    # "First run" — server was down, action was queued
    queue_run1 = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue_run1.initialize()
    assert queue_run1.pending_count == 1

    # "Restart" — new queue instance, same repo (DB persists)
    queue_run2 = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    await queue_run2.initialize()
    assert queue_run2.pending_count == 1   # loaded from DB

    mock_client = AsyncMock()
    mock_client.parse_text = AsyncMock()

    with patch('application.services.action_retry_queue.DiaryApiClient', return_value=mock_client):
        succeeded, failed = await queue_run2.retry_once()

    assert succeeded == 1
    assert failed == 0
    assert queue_run2.pending_count == 0
    assert action.id not in repo.store


# ── pending_count ─────────────────────────────────────────────────────────────

async def test_pending_count_reflects_queue_size() -> None:
    repo = InMemoryRepo()
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)

    assert queue.pending_count == 0
    await queue.enqueue_parse_text(text='a', occurred_at=_NOW, source_type='telegram_live')
    assert queue.pending_count == 1
    await queue.enqueue_create_event(
        event_type='diaper', occurred_at=_NOW, payload={}, source_type='telegram_quick_action'
    )
    assert queue.pending_count == 2


# ── background loop ───────────────────────────────────────────────────────────

async def test_retry_loop_calls_retry_once_after_interval() -> None:
    """Drive _retry_loop directly: instant sleep on first call, CancelledError on second."""
    action = _make_parse_text_action()
    repo = InMemoryRepo([action])
    queue = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS, retry_interval_min=10)
    await queue.initialize()

    call_count = 0

    async def _patched_retry_once():
        nonlocal call_count
        call_count += 1
        return (1, 0)

    queue.retry_once = _patched_retry_once  # type: ignore[method-assign]

    sleep_calls = 0

    async def _limited_sleep(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise asyncio.CancelledError('test stop')
        # first call: skip the 10-minute wait and fall through to retry

    with patch('application.services.action_retry_queue.asyncio.sleep', side_effect=_limited_sleep):
        try:
            await queue._retry_loop()
        except asyncio.CancelledError:
            pass

    assert call_count >= 1
    assert sleep_calls >= 1


async def test_start_is_idempotent() -> None:
    queue = _make_queue()
    queue.start()
    task1 = queue._task
    queue.start()   # second call must not create a new task
    assert queue._task is task1
    queue.stop()


async def test_stop_cancels_task() -> None:
    queue = _make_queue()
    queue.start()
    assert queue._task is not None
    queue.stop()
    assert queue._task is None


# ── singleton ─────────────────────────────────────────────────────────────────

async def test_set_and_get_retry_queue() -> None:
    repo = InMemoryRepo()
    q = ActionRetryQueue(repo=repo, diary_api_settings=_API_SETTINGS)
    set_retry_queue(q)
    assert get_retry_queue() is q


async def test_get_retry_queue_raises_before_set() -> None:
    import application.services.action_retry_queue as mod
    original = mod._queue
    mod._queue = None
    try:
        with pytest.raises(RuntimeError, match='not been initialised'):
            get_retry_queue()
    finally:
        mod._queue = original


# ── _execute helper ───────────────────────────────────────────────────────────

async def test_execute_parse_text_calls_client() -> None:
    action = _make_parse_text_action()
    client = AsyncMock()
    client.parse_text = AsyncMock()

    await _execute(client, action)

    client.parse_text.assert_called_once()
    kwargs = client.parse_text.call_args.kwargs
    assert kwargs['text'] == 'Заснул'
    assert kwargs['source_type'] == 'telegram_live'


async def test_execute_create_event_calls_client() -> None:
    action = _make_create_event_action()
    client = AsyncMock()
    client.create_event = AsyncMock()

    await _execute(client, action)

    client.create_event.assert_called_once()
    kwargs = client.create_event.call_args.kwargs
    assert kwargs['event_type'] == 'sleep_start'
    assert kwargs['source_type'] == 'telegram_quick_action'


async def test_execute_unknown_action_type_raises() -> None:
    action = PendingAction(action_type='unknown', created_at=_NOW.isoformat())
    client = AsyncMock()

    with pytest.raises(ValueError, match='Unknown action_type'):
        await _execute(client, action)


# ── SqlPendingActionsRepository SQL paths ─────────────────────────────────────

def _make_session_mock() -> tuple[MagicMock, MagicMock]:
    """Returns (session_factory_mock, session_mock)."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session
    return factory, session


async def test_sql_repo_setup_creates_table() -> None:
    from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository

    engine = AsyncMock()
    conn = AsyncMock()
    conn.run_sync = AsyncMock()
    engine.begin = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=conn)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    factory, _ = _make_session_mock()
    repo = SqlPendingActionsRepository(engine, factory)
    await repo.setup()

    conn.run_sync.assert_called_once()


async def test_sql_repo_upsert_executes_statement() -> None:
    from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository

    engine = AsyncMock()
    factory, session = _make_session_mock()
    repo = SqlPendingActionsRepository(engine, factory)

    action = _make_parse_text_action()
    await repo.upsert(action)

    session.execute.assert_called_once()


async def test_sql_repo_delete_executes_statement() -> None:
    from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository

    engine = AsyncMock()
    factory, session = _make_session_mock()
    repo = SqlPendingActionsRepository(engine, factory)

    await repo.delete('some-id')

    session.execute.assert_called_once()


async def test_sql_repo_load_all_returns_domain_objects() -> None:
    from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository
    from infrastructure.models.pending_action import PendingActionModel

    engine = AsyncMock()
    factory, session = _make_session_mock()

    # Build a fake ORM row
    action = _make_parse_text_action()
    model_row = PendingActionModel(
        id=action.id,
        action_type=action.action_type,
        created_at=action.created_at,
        attempt_count=action.attempt_count,
        text=action.text,
        occurred_at=action.occurred_at,
        source_type=action.source_type,
        source_message_id=action.source_message_id,
        source_chat_id=action.source_chat_id,
        event_type=action.event_type,
        payload=action.payload,
    )

    scalars_mock = MagicMock()
    scalars_mock.return_value = [model_row]
    result_mock = MagicMock()
    result_mock.scalars = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)

    repo = SqlPendingActionsRepository(engine, factory)
    result = await repo.load_all()

    assert len(result) == 1
    assert result[0].id == action.id
    assert result[0].text == action.text


# ── handler integration ───────────────────────────────────────────────────────

def _make_message(text: str = '', message_id: int = 1, chat_id: int = 100) -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.full_name = 'Mila'
    msg.date = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
    msg.reply = AsyncMock(return_value=AsyncMock(message_id=9001))
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    msg.bot = AsyncMock()
    return msg


def _make_fsm() -> AsyncMock:
    state = AsyncMock()
    _data: dict = {}
    state.get_data = AsyncMock(side_effect=lambda: dict(_data))
    state.update_data = AsyncMock(side_effect=lambda d=None, **kw: _data.update(d or {}, **kw))
    state.set_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


async def test_handle_text_enqueues_on_parse_text_failure() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Заснул')
    state = _make_fsm()
    api = AsyncMock()
    api.parse_text = AsyncMock(side_effect=Exception('server down'))

    retry_queue = AsyncMock()
    retry_queue.enqueue_parse_text = AsyncMock()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers._get_retry_queue', return_value=retry_queue), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        await handle_text(msg, state)

    retry_queue.enqueue_parse_text.assert_called_once()
    kwargs = retry_queue.enqueue_parse_text.call_args.kwargs
    assert kwargs['text'] == 'Заснул'
    assert kwargs['source_type'] == 'telegram_live'
    msg.reply.assert_called_once()
    assert 'повторю' in msg.reply.call_args.args[0].lower()


async def test_cb_quick_action_enqueues_on_create_event_failure() -> None:
    from infrastructure.telegram.handlers import cb_quick_action

    query = AsyncMock()
    query.data = 'sleep_start'
    query.answer = AsyncMock()
    query.message = AsyncMock()

    api = AsyncMock()
    api.create_event = AsyncMock(side_effect=Exception('server down'))

    retry_queue = AsyncMock()
    retry_queue.enqueue_create_event = AsyncMock()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers._get_retry_queue', return_value=retry_queue):
        await cb_quick_action(query)

    retry_queue.enqueue_create_event.assert_called_once()
    kwargs = retry_queue.enqueue_create_event.call_args.kwargs
    assert kwargs['event_type'] == 'sleep_start'
    assert kwargs['source_type'] == 'telegram_quick_action'
    query.answer.assert_called()
    assert 'повторю' in query.answer.call_args.args[0].lower()


async def test_handle_text_does_not_enqueue_on_success() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Заснул')
    state = _make_fsm()
    api = AsyncMock()
    api.parse_text = AsyncMock(return_value={'events': []})

    retry_queue = AsyncMock()
    retry_queue.enqueue_parse_text = AsyncMock()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers._get_retry_queue', return_value=retry_queue), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        await handle_text(msg, state)

    retry_queue.enqueue_parse_text.assert_not_called()


async def test_cb_quick_action_does_not_enqueue_on_success() -> None:
    from infrastructure.telegram.handlers import cb_quick_action

    query = AsyncMock()
    query.data = 'sleep_start'
    query.answer = AsyncMock()
    query.message = AsyncMock()

    api = AsyncMock()
    api.create_event = AsyncMock(return_value={})

    retry_queue = AsyncMock()
    retry_queue.enqueue_create_event = AsyncMock()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers._get_retry_queue', return_value=retry_queue):
        await cb_quick_action(query)

    retry_queue.enqueue_create_event.assert_not_called()
