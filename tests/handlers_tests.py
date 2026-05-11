"""Handler unit tests using mocked aiogram objects and DiaryApiClient."""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

_SAMPLE_UUID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
_SUMMARY_MSG_ID = 9001


def _make_message(
    text: str = '',
    message_id: int = 1,
    chat_id: int = 100,
    message_thread_id: int | None = None,
) -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.message_id = message_id
    msg.message_thread_id = message_thread_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.full_name = 'Mila'
    msg.date = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
    msg.reply = AsyncMock(return_value=AsyncMock(message_id=_SUMMARY_MSG_ID))
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.edit_message_text = AsyncMock()
    return msg


_PROMPT_MSG_ID = 9002


def _make_callback(
    data: str,
    message_id: int = _SUMMARY_MSG_ID,
    chat_id: int = 100,
    message_thread_id: int | None = None,
) -> MagicMock:
    query = AsyncMock()
    query.data = data
    query.answer = AsyncMock()
    msg = AsyncMock()
    msg.message_id = message_id
    msg.message_thread_id = message_thread_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = AsyncMock()
    msg.bot.send_message = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.delete = AsyncMock()
    prompt_msg = AsyncMock()
    prompt_msg.message_id = _PROMPT_MSG_ID
    msg.answer = AsyncMock(return_value=prompt_msg)
    query.message = msg
    return query


def _make_fsm(initial_data: dict | None = None) -> AsyncMock:
    state = AsyncMock()
    _data = dict(initial_data or {})
    state.get_data = AsyncMock(side_effect=lambda: dict(_data))

    async def _update_data(new: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if new:
            _data.update(new)
        _data.update(kwargs)

    async def _set_data(new: dict[str, Any]) -> None:
        _data.clear()
        _data.update(new)

    state.update_data = AsyncMock(side_effect=_update_data)
    state.set_data = AsyncMock(side_effect=_set_data)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def _make_api_client(**overrides: Any) -> AsyncMock:
    client = AsyncMock()
    client.parse_text = AsyncMock(return_value={'events': [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]})
    client.create_event = AsyncMock(return_value={})
    client.get_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {},
    })
    client.update_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {},
    })
    client.delete_event = AsyncMock()
    client.ask = AsyncMock(return_value={'answer': 'ok'})
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# ── handle_text ───────────────────────────────────────────────────────────────

async def test_handle_text_replies_with_keyboard() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Заснул')
    state = _make_fsm()
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        await handle_text(msg, state)

    api.parse_text.assert_called_once()
    msg.reply.assert_called_once()
    call_kwargs = msg.reply.call_args
    assert call_kwargs.kwargs.get('reply_markup') is not None or (
        len(call_kwargs.args) > 1 or call_kwargs.kwargs
    )


async def test_handle_text_parses_events_from_configured_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Заснул', message_thread_id=10)
    state = _make_fsm()
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = None
        await handle_text(msg, state)

    api.parse_text.assert_called_once()
    msg.reply.assert_called_once()


async def test_handle_text_ignores_events_outside_configured_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Заснул', message_thread_id=20)
    state = _make_fsm()
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = None
        await handle_text(msg, state)

    api.parse_text.assert_not_called()
    msg.reply.assert_not_called()


# ── cb_quick_action (regression) ──────────────────────────────────────────────

async def test_cb_quick_action_no_edit_keyboard() -> None:
    from infrastructure.telegram.handlers import cb_quick_action

    query = _make_callback('sleep_start')
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await cb_quick_action(query)

    api.create_event.assert_called_once()
    # The quick action reply should NOT include an edit keyboard (no edit_reply_markup)
    query.message.edit_reply_markup.assert_not_called()


# ── ev_del ────────────────────────────────────────────────────────────────────

async def test_cb_ev_del_deletes_empty_summary_message() -> None:
    from infrastructure.telegram.handlers import cb_ev_del

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_del:{_SAMPLE_UUID}')
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await cb_ev_del(query, state)

    api.delete_event.assert_called_once_with(_SAMPLE_UUID)
    query.message.delete.assert_called_once()
    query.message.edit_text.assert_not_called()
    query.message.answer.assert_not_called()


# ── ev_tm ─────────────────────────────────────────────────────────────────────

async def test_cb_ev_tm_sets_state() -> None:
    from infrastructure.telegram.handlers import cb_ev_tm

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_tm:{_SAMPLE_UUID}')

    await cb_ev_tm(query, state)

    from infrastructure.telegram.handlers import EditState
    state.set_state.assert_called_once_with(EditState.waiting_for_new_time)
    state.update_data.assert_called()


async def test_cb_ev_tm_stores_prompt_message_id() -> None:
    from infrastructure.telegram.handlers import cb_ev_tm

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_tm:{_SAMPLE_UUID}')

    await cb_ev_tm(query, state)

    all_calls = state.update_data.call_args_list
    stored: dict = {}
    for call in all_calls:
        if call.kwargs:
            stored.update(call.kwargs)
        if call.args and isinstance(call.args[0], dict):
            stored.update(call.args[0])
    assert stored.get('edit_prompt_message_id') == _PROMPT_MSG_ID


# ── handle_new_time ───────────────────────────────────────────────────────────

async def test_handle_new_time_valid_updates_event() -> None:
    from infrastructure.telegram.handlers import handle_new_time

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({
        str(_SUMMARY_MSG_ID): events,
        'edit_event_id': _SAMPLE_UUID,
        'edit_summary_message_id': _SUMMARY_MSG_ID,
        'edit_original_date_iso': '2026-05-10T10:00:00+03:00',
        'edit_prompt_message_id': _PROMPT_MSG_ID,
    })
    msg = _make_message('21:55', message_id=200, chat_id=100)
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await handle_new_time(msg, state)

    api.update_event.assert_called_once()
    call_kwargs = api.update_event.call_args.kwargs
    assert call_kwargs.get('occurred_at') is not None
    occurred = call_kwargs['occurred_at']
    assert occurred.hour == 21
    assert occurred.minute == 55
    state.clear.assert_called_once()
    msg.bot.delete_message.assert_called_once_with(chat_id=100, message_id=_PROMPT_MSG_ID)
    msg.delete.assert_called_once()


async def test_handle_new_time_deletes_user_message_without_prompt() -> None:
    from infrastructure.telegram.handlers import handle_new_time

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({
        str(_SUMMARY_MSG_ID): events,
        'edit_event_id': _SAMPLE_UUID,
        'edit_summary_message_id': _SUMMARY_MSG_ID,
        'edit_original_date_iso': '2026-05-10T10:00:00+03:00',
    })
    msg = _make_message('21:55', message_id=200, chat_id=100)
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await handle_new_time(msg, state)

    msg.bot.delete_message.assert_not_called()
    msg.delete.assert_called_once()


async def test_handle_new_time_invalid_reprompts() -> None:
    from infrastructure.telegram.handlers import handle_new_time

    state = _make_fsm({'edit_event_id': _SAMPLE_UUID})
    msg = _make_message('not-a-time')
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await handle_new_time(msg, state)

    api.update_event.assert_not_called()
    state.clear.assert_not_called()
    msg.answer.assert_called_once()


# ── ev_tp ─────────────────────────────────────────────────────────────────────

async def test_cb_ev_tp_swaps_keyboard() -> None:
    from infrastructure.telegram.handlers import cb_ev_tp

    query = _make_callback(f'ev_tp:{_SAMPLE_UUID}')
    await cb_ev_tp(query)

    query.message.edit_reply_markup.assert_called_once()
    keyboard = query.message.edit_reply_markup.call_args.kwargs.get('reply_markup')
    assert keyboard is not None


# ── ev_sub ────────────────────────────────────────────────────────────────────

async def test_cb_ev_sub_preserves_duration_min() -> None:
    from infrastructure.telegram.handlers import cb_ev_sub

    old_payload = {'duration_min': 30}
    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_end', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': old_payload},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_sub:{_SAMPLE_UUID}:bath')
    api = _make_api_client()
    api.get_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'sleep_end', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': old_payload,
    })
    api.update_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'bath', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {'duration_min': 30},
    })

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await cb_ev_sub(query, state)

    _, kwargs = api.update_event.call_args
    assert kwargs['payload'].get('duration_min') == 30
    assert kwargs['event_type'] == 'bath'


async def test_cb_ev_sub_no_compatible_fields() -> None:
    from infrastructure.telegram.handlers import cb_ev_sub

    old_payload = {'grams': 4200}
    events = [
        {'id': _SAMPLE_UUID, 'type': 'weight', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': old_payload},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_sub:{_SAMPLE_UUID}:bath')
    api = _make_api_client()
    api.get_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'weight', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': old_payload,
    })
    api.update_event = AsyncMock(return_value={
        'id': _SAMPLE_UUID, 'type': 'bath', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {},
    })

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await cb_ev_sub(query, state)

    _, kwargs = api.update_event.call_args
    # 'grams' is not in _COMMON_FIELDS — should not be carried over
    assert 'grams' not in kwargs.get('payload', {})


# ── ev_back ───────────────────────────────────────────────────────────────────

async def test_cb_ev_back_restores_keyboard_without_api_call() -> None:
    from infrastructure.telegram.handlers import cb_ev_back

    events = [
        {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    ]
    state = _make_fsm({str(_SUMMARY_MSG_ID): events})
    query = _make_callback(f'ev_back:{_SAMPLE_UUID}')
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api):
        await cb_ev_back(query, state)

    query.message.edit_reply_markup.assert_called_once()
    api.get_event.assert_not_called()
    api.update_event.assert_not_called()


# ── ev_done ───────────────────────────────────────────────────────────────────

async def test_cb_ev_done_deletes_message() -> None:
    from infrastructure.telegram.handlers import cb_ev_done

    state = _make_fsm({str(_SUMMARY_MSG_ID): []})
    query = _make_callback('ev_done')

    await cb_ev_done(query, state)

    query.message.delete.assert_called_once()
    query.message.edit_reply_markup.assert_not_called()


# ── question prefix ───────────────────────────────────────────────────────────

async def test_handle_text_question_prefix_routes_to_ask() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('? Сколько спал вчера?')
    state = _make_fsm()
    api = _make_api_client()
    api.ask = AsyncMock(return_value={'answer': '8 часов'})

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        await handle_text(msg, state)

    api.ask.assert_called_once()
    api.parse_text.assert_not_called()


async def test_handle_text_question_prefix_answers_in_configured_question_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('? Сколько спал вчера?', message_thread_id=30)
    state = _make_fsm()
    api = _make_api_client(ask=AsyncMock(return_value={'answer': '8 часов'}))

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = 30
        await handle_text(msg, state)

    api.ask.assert_called_once_with('Сколько спал вчера?')
    msg.answer.assert_called_once()
    assert 'message_thread_id' not in msg.answer.call_args.kwargs
    msg.bot.send_message.assert_not_called()


async def test_handle_text_plain_text_answers_in_configured_question_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Сколько спал вчера?', message_thread_id=30)
    state = _make_fsm()
    api = _make_api_client(ask=AsyncMock(return_value={'answer': '8 часов'}))

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = 30
        await handle_text(msg, state)

    api.ask.assert_called_once_with('Сколько спал вчера?')
    api.parse_text.assert_not_called()
    msg.answer.assert_called_once()


async def test_handle_text_question_topic_takes_precedence_over_event_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('Сколько спал вчера?', message_thread_id=30)
    state = _make_fsm()
    api = _make_api_client(ask=AsyncMock(return_value={'answer': '8 часов'}))

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 30
        mock_settings.telegram.question_topic_id = 30
        await handle_text(msg, state)

    api.ask.assert_called_once_with('Сколько спал вчера?')
    api.parse_text.assert_not_called()


async def test_handle_text_question_prefix_ignored_outside_configured_question_topic() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = _make_message('? Сколько спал вчера?', message_thread_id=20)
    state = _make_fsm()
    api = _make_api_client(ask=AsyncMock(return_value={'answer': '8 часов'}))

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.allowed_chat_ids = []
        mock_settings.telegram.allowed_authors = []
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = 30
        await handle_text(msg, state)

    api.ask.assert_not_called()
    api.parse_text.assert_not_called()
    msg.answer.assert_not_called()


async def test_handle_question_in_state_keeps_event_topic_parsing_available() -> None:
    from infrastructure.telegram.handlers import handle_question_in_state

    msg = _make_message('Заснул', message_thread_id=10)
    state = _make_fsm()
    api = _make_api_client()

    with patch('infrastructure.telegram.handlers._get_client', return_value=api), \
         patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.event_topic_id = 10
        mock_settings.telegram.question_topic_id = 30
        await handle_question_in_state(msg, state)

    api.parse_text.assert_called_once()
    api.ask.assert_not_called()
    state.clear.assert_not_called()


async def test_cb_ask_mode_prompts_in_configured_question_topic_from_other_topic() -> None:
    from infrastructure.telegram.handlers import cb_ask_mode

    query = _make_callback('ask_mode', message_thread_id=20)
    state = _make_fsm()

    with patch('infrastructure.telegram.handlers.settings') as mock_settings:
        mock_settings.telegram.question_topic_id = 30
        await cb_ask_mode(query, state)

    query.message.answer.assert_not_called()
    query.message.bot.send_message.assert_called_once_with(
        chat_id=100,
        message_thread_id=30,
        text='Задайте вопрос:',
    )
