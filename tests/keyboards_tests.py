"""Pure-function tests for keyboard builders."""
import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from infrastructure.telegram.keyboards import (
    ACTION_MAP,
    event_summary_keyboard,
    type_change_keyboard,
)

_SAMPLE_UUID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

_EVENTS = [
    {'id': _SAMPLE_UUID, 'type': 'sleep_start', 'occurred_at': '2026-05-10T10:00:00+03:00', 'payload': {}},
    {'id': 'bbbbbbbb-0000-0000-0000-000000000000', 'type': 'diaper', 'occurred_at': '2026-05-10T10:05:00+03:00', 'payload': {'kind': 'pee'}},
]


def _all_buttons(kb: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [btn for row in kb.inline_keyboard for btn in row]


def test_event_summary_keyboard_row_count() -> None:
    kb = event_summary_keyboard(_EVENTS)
    # one row per event + one Done row
    assert len(kb.inline_keyboard) == len(_EVENTS) + 1


def test_event_summary_keyboard_callback_data_prefixes() -> None:
    kb = event_summary_keyboard(_EVENTS)
    event_rows = kb.inline_keyboard[:-1]
    for i, (event, row) in enumerate(zip(_EVENTS, event_rows)):
        eid = event['id']
        cbs = [btn.callback_data for btn in row if btn.callback_data is not None]
        assert any(cb.startswith(f'ev_tm:{eid}') for cb in cbs)
        assert any(cb.startswith(f'ev_tp:{eid}') for cb in cbs)
        assert any(cb.startswith(f'ev_del:{eid}') for cb in cbs)


def test_event_summary_keyboard_done_button() -> None:
    kb = event_summary_keyboard(_EVENTS)
    last_row = kb.inline_keyboard[-1]
    assert any(btn.callback_data == 'ev_done' for btn in last_row)


def test_type_change_keyboard_has_action_map_entries() -> None:
    kb = type_change_keyboard(_SAMPLE_UUID)
    all_cbs = [btn.callback_data for btn in _all_buttons(kb)]
    for aid in ACTION_MAP:
        expected = f'ev_sub:{_SAMPLE_UUID}:{aid}'
        assert expected in all_cbs, f'Missing button for action {aid}'


def test_type_change_keyboard_has_back_button() -> None:
    kb = type_change_keyboard(_SAMPLE_UUID)
    all_cbs = [btn.callback_data for btn in _all_buttons(kb)]
    assert f'ev_back:{_SAMPLE_UUID}' in all_cbs


def test_all_callback_data_within_64_bytes() -> None:
    for kb in [event_summary_keyboard(_EVENTS), type_change_keyboard(_SAMPLE_UUID)]:
        for btn in _all_buttons(kb):
            cb = btn.callback_data or ''
            assert len(cb.encode()) <= 64, f'callback_data too long: {cb!r} ({len(cb.encode())} bytes)'
