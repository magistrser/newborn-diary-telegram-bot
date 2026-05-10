from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domain.quick_actions import ACTION_MAP, QUICK_ACTIONS

_MOSCOW_TZ = ZoneInfo('Europe/Moscow')

__all__ = ['ACTION_MAP', 'event_summary_keyboard', 'main_keyboard', 'type_change_keyboard']

# Sub-keyboard sections: (section_label, [action_ids])
_SECTIONS = [
    ('🍼 Кормление', ['feed_left', 'feed_right', 'feed_bottle_formula', 'feed_bottle_expr', 'pump']),
    ('🚼 Подгузник', ['diaper_pee', 'diaper_poo', 'diaper_unknown']),
    ('😴 Сон', ['sleep_start', 'sleep_end']),
    ('🤸 Активность', ['bath', 'tummy_time']),
    ('🤧 Симптомы', ['spit_up_small', 'spit_up_large', 'gas']),
    ('💊 Прочее', ['vitamin_d', 'ask_mode']),
]

_ACTION_BY_ID = {a[0]: a for a in QUICK_ACTIONS}


def event_summary_keyboard(events: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """One row per event (time/type/delete buttons) plus a Done row."""
    rows: list[list[InlineKeyboardButton]] = []
    for e in events:
        eid = e['id']
        _occ_raw = e.get('occurred_at', '')
        try:
            occ = datetime.fromisoformat(_occ_raw).astimezone(_MOSCOW_TZ).strftime('%H:%M')
        except (ValueError, OverflowError):
            occ = _occ_raw[11:16]
        rows.append([
            InlineKeyboardButton(text=f'🕒 {occ}', callback_data=f'ev_tm:{eid}'),
            InlineKeyboardButton(text='🔀', callback_data=f'ev_tp:{eid}'),
            InlineKeyboardButton(text='🗑', callback_data=f'ev_del:{eid}'),
        ])
    rows.append([InlineKeyboardButton(text='✅ Готово', callback_data='ev_done')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def type_change_keyboard(event_id: str) -> InlineKeyboardMarkup:
    """Quick-action sub-keyboard for changing an event's type."""
    rows: list[list[InlineKeyboardButton]] = []
    for section_label, action_ids in _SECTIONS:
        rows.append([InlineKeyboardButton(text=section_label, callback_data='noop')])
        row: list[InlineKeyboardButton] = []
        for aid in action_ids:
            action = _ACTION_BY_ID[aid]
            if action[2] is None:  # skip special actions (ask_mode)
                continue
            row.append(InlineKeyboardButton(
                text=action[1],
                callback_data=f'ev_sub:{event_id}:{aid}',
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    rows.append([InlineKeyboardButton(text='« Назад', callback_data=f'ev_back:{event_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_keyboard() -> InlineKeyboardMarkup:
    """Sectioned keyboard: section header (disabled button) + 2-per-row actions."""
    rows: list[list[InlineKeyboardButton]] = []
    for section_label, action_ids in _SECTIONS:
        rows.append([InlineKeyboardButton(text=section_label, callback_data='noop')])
        row: list[InlineKeyboardButton] = []
        for aid in action_ids:
            action = _ACTION_BY_ID[aid]
            row.append(InlineKeyboardButton(text=action[1], callback_data=aid))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)
