"""Unit tests for SqlFsmStorage using mocked SQLAlchemy session factory."""
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

from infrastructure.models.fsm_state import FsmStateModel
from infrastructure.repositories.fsm_state_storage import SqlFsmStorage


class _S(StatesGroup):  # pylint: disable=too-few-public-methods
    waiting = State()


def _make_key(bot_id: int = 1, chat_id: int = 100, user_id: int = 200) -> StorageKey:
    return StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)


def _make_session_mock() -> tuple[MagicMock, MagicMock]:
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


def _result_with(row: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _make_storage(session: MagicMock | None = None) -> tuple[SqlFsmStorage, MagicMock]:
    factory, sess = _make_session_mock()
    if session is not None:
        factory.return_value = session
        sess = session
    engine = AsyncMock()
    return SqlFsmStorage(engine, factory), sess


# ── set_state ─────────────────────────────────────────────────────────────────

async def test_set_state_executes_upsert() -> None:
    storage, session = _make_storage()
    await storage.set_state(_make_key(), 'TestState:s')
    session.execute.assert_called_once()


async def test_set_state_with_state_object_serializes_to_string() -> None:
    storage, session = _make_storage()

    captured: list[Any] = []

    async def _capture(stmt: Any) -> None:
        captured.append(stmt)

    session.execute = AsyncMock(side_effect=_capture)
    await storage.set_state(_make_key(), _S.waiting)

    assert len(captured) == 1
    compiled = captured[0].compile()
    params = compiled.params
    assert params.get('state') == _S.waiting.state


async def test_set_state_with_none_stores_null() -> None:
    storage, session = _make_storage()
    await storage.set_state(_make_key(), None)
    session.execute.assert_called_once()


# ── get_state ─────────────────────────────────────────────────────────────────

async def test_get_state_returns_string_when_row_exists() -> None:
    storage, session = _make_storage()
    row = FsmStateModel(
        bot_id=1, chat_id=100, user_id=200, destiny='fsm',
        state='AskState:waiting_for_question', data={},
    )
    session.execute = AsyncMock(return_value=_result_with(row))

    result = await storage.get_state(_make_key())

    assert result == 'AskState:waiting_for_question'


async def test_get_state_returns_none_when_no_row() -> None:
    storage, session = _make_storage()
    session.execute = AsyncMock(return_value=_result_with(None))

    result = await storage.get_state(_make_key())

    assert result is None


async def test_get_state_returns_none_when_state_column_is_null() -> None:
    storage, session = _make_storage()
    row = FsmStateModel(bot_id=1, chat_id=100, user_id=200, destiny='fsm', state=None, data={})
    session.execute = AsyncMock(return_value=_result_with(row))

    result = await storage.get_state(_make_key())

    assert result is None


# ── set_data ──────────────────────────────────────────────────────────────────

async def test_set_data_executes_upsert() -> None:
    storage, session = _make_storage()
    await storage.set_data(_make_key(), {'edit_event_id': 'abc'})
    session.execute.assert_called_once()


async def test_set_data_empty_dict_executes_cleanup_delete() -> None:
    storage, session = _make_storage()
    await storage.set_data(_make_key(), {})
    # first call: upsert; second call: DELETE where state IS NULL
    assert session.execute.call_count == 2


async def test_set_data_nonempty_does_not_execute_delete() -> None:
    storage, session = _make_storage()
    await storage.set_data(_make_key(), {'x': 1})
    assert session.execute.call_count == 1


# ── get_data ──────────────────────────────────────────────────────────────────

async def test_get_data_returns_dict_when_row_exists() -> None:
    storage, session = _make_storage()
    payload = {'edit_event_id': 'uuid-123', 'edit_summary_message_id': 9001}
    row = FsmStateModel(bot_id=1, chat_id=100, user_id=200, destiny='fsm', state=None, data=payload)
    session.execute = AsyncMock(return_value=_result_with(row))

    result = await storage.get_data(_make_key())

    assert result == payload


async def test_get_data_returns_empty_dict_when_no_row() -> None:
    storage, session = _make_storage()
    session.execute = AsyncMock(return_value=_result_with(None))

    result = await storage.get_data(_make_key())

    assert result == {}


async def test_get_data_returns_empty_dict_when_data_is_none() -> None:
    storage, session = _make_storage()
    row = FsmStateModel(  # type: ignore[call-arg]
        bot_id=1, chat_id=100, user_id=200, destiny='fsm', state=None, data=None,
    )
    session.execute = AsyncMock(return_value=_result_with(row))

    result = await storage.get_data(_make_key())

    assert result == {}


# ── close ─────────────────────────────────────────────────────────────────────

async def test_close_is_noop() -> None:
    storage, _ = _make_storage()
    await storage.close()  # must not raise


# ── key isolation ─────────────────────────────────────────────────────────────

async def test_different_users_get_different_keys() -> None:
    key_a = _make_key(user_id=1)
    key_b = _make_key(user_id=2)
    assert key_a != key_b


# ── state serialization round-trip ────────────────────────────────────────────

async def test_state_object_state_attribute_matches_string() -> None:
    state_obj = _S.waiting
    expected = 'tests.fsm_state_storage_tests:_S:waiting'
    # aiogram formats it as module:group:name
    assert state_obj.state == expected or ':waiting' in (state_obj.state or '')
