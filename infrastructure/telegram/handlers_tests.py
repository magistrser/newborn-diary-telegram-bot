from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.storage.memory import MemoryStorage


async def _make_message(text: str, chat_id: int = -1001, author: str = 'Mila') -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.message_id = 1
    msg.from_user.full_name = author
    from datetime import datetime, timezone
    msg.date = datetime(2026, 5, 9, 11, 0, 0, tzinfo=timezone.utc)
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    return msg


async def test_handle_text_calls_parse_text() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = await _make_message('Правая')

    mock_result = {'events': [{'type': 'feed_breast', 'occurred_at': '2026-05-09T11:00:00Z', 'payload': {'side': 'right'}}]}

    with patch('infrastructure.telegram.handlers._get_client') as mock_get_client:
        mock_client = AsyncMock()
        mock_client.parse_text = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        state = MagicMock()
        state.get_state = AsyncMock(return_value=None)

        await handle_text(msg, state)

    mock_client.parse_text.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert 'правая' in reply_text.lower() or 'Сохранил' in reply_text


async def test_question_prefix_routes_to_ask() -> None:
    from infrastructure.telegram.handlers import handle_text

    msg = await _make_message('? Сколько спал вчера?')

    with patch('infrastructure.telegram.handlers._get_client') as mock_get_client:
        mock_client = AsyncMock()
        mock_client.ask = AsyncMock(return_value={'answer': '8 часов'})
        mock_get_client.return_value = mock_client

        state = MagicMock()
        state.get_state = AsyncMock(return_value=None)

        await handle_text(msg, state)

    mock_client.ask.assert_awaited_once()
