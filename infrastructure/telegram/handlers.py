"""
Telegram message, command, and callback handlers.
All handlers are registered on a single Router defined here.
"""
import html
import logging
import re
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from application.services.action_retry_queue import ActionRetryQueue, get_retry_queue
from application.services.diary_api_client import DiaryApiClient
from infrastructure.telegram.keyboards import (
    ACTION_MAP,
    event_summary_keyboard,
    main_keyboard,
    type_change_keyboard,
)
from settings import settings

_MOSCOW_TZ = ZoneInfo('Europe/Moscow')
_COMMON_FIELDS = {'duration_min'}  # payload fields preserved across type changes

logger = logging.getLogger(__name__)

router = Router(name='diary')


class AskState(StatesGroup):
    waiting_for_question = State()


class EditState(StatesGroup):
    waiting_for_new_time = State()


def _is_allowed(chat_id: int, author: str | None) -> bool:
    allowed_chats = settings.telegram.allowed_chat_ids
    allowed_authors = settings.telegram.allowed_authors
    if allowed_chats and chat_id not in allowed_chats:
        return False
    if allowed_authors and author and author not in allowed_authors:
        return False
    return True


def _get_client() -> DiaryApiClient:
    return DiaryApiClient(settings.diary_api)


def _get_retry_queue() -> ActionRetryQueue:
    return get_retry_queue()


def _occ_str(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw).astimezone(_MOSCOW_TZ).strftime('%Y-%m-%d %H:%M')
    except (ValueError, OverflowError):
        return raw[:16].replace('T', ' ')


def _dur_str(p: dict) -> str:
    dur = p.get('duration_min')
    return f' ({dur} мин)' if dur else ''


def _fmt_feed_breast(occ: str, p: dict, d: str) -> str:
    side = 'левая' if p.get('side') == 'left' else 'правая'
    return f'🍼 {occ} грудь ({side}){d}'


def _fmt_feed_bottle(occ: str, p: dict, _d: str) -> str:
    contents = 'смесь' if p.get('contents') == 'formula' else 'сцеженное'
    vol = f' {p["volume_ml"]} мл' if p.get('volume_ml') else ''
    return f'🍶 {occ} бутылочка ({contents}){vol}'


def _fmt_pump(occ: str, p: dict, d: str) -> str:
    vol = f' {p["volume_ml"]} мл' if p.get('volume_ml') else ''
    return f'🥛 {occ} сцедила{vol}{d}'


def _fmt_diaper(occ: str, p: dict, _d: str) -> str:
    kind_map = {'pee': '💧 пописал', 'poo': '💩 покакал', 'both': '💩💧 всё', 'unknown': '🚼 подгузник'}
    return f"{kind_map.get(p.get('kind', 'unknown'), '🚼 подгузник')} {occ}"


def _fmt_weight(occ: str, p: dict, _d: str) -> str:
    return f'⚖️ {occ} вес {p.get("grams", "?")} г'


def _fmt_temperature(occ: str, p: dict, _d: str) -> str:
    return f'🌡 {occ} температура {p.get("celsius", "?")}°C'


def _fmt_medication(occ: str, p: dict, _d: str) -> str:
    dose = f' {p["dose_ml"]} мл' if p.get('dose_ml') else ''
    return f'💊 {occ} {p.get("name", "лекарство")}{dose}'


def _fmt_doctor_visit(occ: str, p: dict, _d: str) -> str:
    vtype = 'плановый' if p.get('type') == 'routine' else 'по болезни'
    return f'🏥 {occ} врач ({vtype})'


def _fmt_spit_up(occ: str, p: dict, _d: str) -> str:
    vol = 'много' if p.get('volume') == 'large' else 'немного'
    return f'🤧 {occ} срыгнул ({vol})'


def _fmt_crying(occ: str, p: dict, d: str) -> str:
    reason_map = {'hunger': 'голод', 'gas': 'газики', 'unknown': '?'}
    reason = reason_map.get(p.get('reason', 'unknown'), '?')
    return f'😭 {occ} плакал{d} ({reason})'


_EVENT_FORMATTERS: dict[str, Callable[[str, dict, str], str]] = {
    'feed_breast': _fmt_feed_breast,
    'feed_bottle': _fmt_feed_bottle,
    'pump': _fmt_pump,
    'diaper': _fmt_diaper,
    'sleep_start': lambda occ, _p, _d: f'😴 {occ} заснул',
    'sleep_end': lambda occ, _p, d: f'🌅 {occ} проснулся{d}',
    'sleep_interval': lambda occ, _p, _d: f'😴 {occ} сон (интервал)',
    'weight': _fmt_weight,
    'temperature': _fmt_temperature,
    'medication': _fmt_medication,
    'vaccination': lambda occ, p, _d: f'💉 {occ} прививка: {p.get("vaccine", "")}',
    'doctor_visit': _fmt_doctor_visit,
    'bath': lambda occ, _p, d: f'🛁 {occ} купание{d}',
    'tummy_time': lambda occ, _p, d: f'🤸 {occ} на животике{d}',
    'walk': lambda occ, _p, d: f'🚶 {occ} прогулка{d}',
    'spit_up': _fmt_spit_up,
    'crying': _fmt_crying,
    'gas': lambda occ, _p, _d: f'💨 {occ} газики',
    'father_calming': lambda occ, _p, d: f'👨 {occ} страдания папы{d}',
}


def _format_event(e: dict) -> str:
    t = e.get('type', '')
    occ = _occ_str(e.get('occurred_at', ''))
    p = e.get('payload', {})
    d = _dur_str(p)
    formatter = _EVENT_FORMATTERS.get(t)
    return formatter(occ, p, d) if formatter else f'📝 {occ} заметка'


def _format_events(data: dict) -> str:
    events = data.get('events', [])
    if not events:
        return '❓ Не удалось распознать события, сохранил как заметку'
    return '✅ Сохранил:\n' + '\n'.join(_format_event(e) for e in events)


async def _safe_answer(query: CallbackQuery, text: str = '') -> None:
    try:
        await query.answer(text)
    except Exception as exc:
        logger.warning('query.answer failed (stale callback?): %s', exc)


# ── Commands ─────────────────────────────────────────────────────────────────

@router.message(Command('start'))
@router.message(Command('menu'))
async def cmd_menu(message: Message) -> None:
    await message.answer('Выберите действие:', reply_markup=main_keyboard())


@router.message(Command('ask'))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    text = message.text or ''
    question = text.partition(' ')[2].strip()
    if question:
        await _handle_question(message, question)
    else:
        await state.set_state(AskState.waiting_for_question)
        await message.answer('Задайте вопрос:')


# ── Question mode FSM ─────────────────────────────────────────────────────────

@router.message(AskState.waiting_for_question)
async def handle_question_in_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _handle_question(message, message.text or '')


async def _handle_question(message: Message, question: str) -> None:
    try:
        result = await _get_client().ask(question)
        await message.answer(html.escape(result.get('answer', '(нет ответа)')))
    except Exception as exc:
        logger.error('ask failed: %s', exc)
        await message.answer('⚠️ Ошибка при обращении к дневнику. Попробуйте позже.')


# ── Free-form text ────────────────────────────────────────────────────────────

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    author = message.from_user.full_name if message.from_user else None

    if not _is_allowed(chat_id, author):
        return

    text = message.text or ''

    # Route to ask if starts with ?
    if text.startswith('?'):
        await _handle_question(message, text[1:].strip())
        return

    occurred_at = message.date.replace(tzinfo=timezone.utc) if message.date else datetime.now(timezone.utc)
    msg_id = str(message.message_id)

    try:
        result = await _get_client().parse_text(
            text=text,
            occurred_at=occurred_at,
            source_type='telegram_live',
            source_message_id=msg_id,
            source_chat_id=chat_id,
        )
        events = result.get('events', [])
        reply_markup = event_summary_keyboard(events) if events else None
        sent = await message.reply(_format_events(result), reply_markup=reply_markup)
        if events and sent:
            await state.update_data({str(sent.message_id): events})
    except Exception as exc:
        logger.error('parse_text failed: %s', exc)
        await _get_retry_queue().enqueue_parse_text(
            text=text,
            occurred_at=occurred_at,
            source_type='telegram_live',
            source_message_id=msg_id,
            source_chat_id=chat_id,
        )
        await message.reply('⚠️ Не удалось сохранить сообщение — повторю попытку автоматически.')


# ── Inline keyboard callbacks ─────────────────────────────────────────────────

@router.callback_query(F.data == 'ask_mode')
async def cb_ask_mode(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    await state.set_state(AskState.waiting_for_question)
    if query.message:
        await query.message.answer('Задайте вопрос:')


@router.callback_query(F.data.in_(set(ACTION_MAP.keys())))
async def cb_quick_action(query: CallbackQuery) -> None:
    action_id = query.data
    if action_id is None:
        await _safe_answer(query, 'Неизвестное действие')
        return

    await _safe_answer(query)

    event_type, payload = ACTION_MAP[action_id]
    occurred_at = datetime.now(timezone.utc)

    try:
        await _get_client().create_event(
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            source_type='telegram_quick_action',
        )
        if query.message:
            occ = occurred_at.astimezone(_MOSCOW_TZ).strftime('%H:%M')
            await query.message.answer(f'✅ {occ} — {action_id.replace("_", " ")}')
    except Exception as exc:
        logger.error('quick_action failed: %s', exc)
        await _get_retry_queue().enqueue_create_event(
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            source_type='telegram_quick_action',
        )
        await query.answer('⚠️ Ошибка — повторю попытку автоматически')


# ── Event inline edit callbacks ───────────────────────────────────────────────

async def _get_summary_events(state: FSMContext, message_id: int) -> list[dict]:
    data = await state.get_data()
    return data.get(str(message_id), [])


async def _update_summary_events(state: FSMContext, message_id: int, events: list[dict]) -> None:
    await state.update_data({str(message_id): events})


@router.callback_query(F.data.startswith('ev_del:'))
async def cb_ev_del(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    if query.data is None:
        return
    event_id = query.data.split(':', 1)[1]
    msg = query.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return
    try:
        await _get_client().delete_event(event_id)
    except Exception as exc:
        logger.error('delete_event failed: %s', exc)
        if msg:
            await msg.answer('⚠️ Ошибка при удалении')
        return

    events = await _get_summary_events(state, msg.message_id)
    events = [e for e in events if e.get('id') != event_id]
    await _update_summary_events(state, msg.message_id, events)

    if not events:
        await msg.edit_text('Все события удалены', reply_markup=None)
    else:
        await msg.edit_text(_format_events({'events': events}), reply_markup=event_summary_keyboard(events))


@router.callback_query(F.data.startswith('ev_tm:'))
async def cb_ev_tm(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    if query.data is None:
        return
    event_id = query.data.split(':', 1)[1]
    msg = query.message
    if msg is None:
        return

    events = await _get_summary_events(state, msg.message_id)
    event = next((e for e in events if e.get('id') == event_id), None)
    original_date_iso = event.get('occurred_at', '') if event else ''

    await state.set_state(EditState.waiting_for_new_time)
    prompt = await msg.answer('Введите новое время (ЧЧ:ММ):')
    await state.update_data(
        edit_event_id=event_id,
        edit_summary_message_id=msg.message_id,
        edit_original_date_iso=original_date_iso,
        edit_prompt_message_id=prompt.message_id if prompt else None,
    )


@router.message(EditState.waiting_for_new_time)
async def handle_new_time(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    if not re.fullmatch(r'\d{1,2}:\d{2}', text):
        await message.answer('Неверный формат. Введите время как ЧЧ:ММ (например, 13:05):')
        return

    data = await state.get_data()
    event_id: str = data.get('edit_event_id', '')
    summary_msg_id: int = data.get('edit_summary_message_id', 0)
    original_date_iso: str = data.get('edit_original_date_iso', '')

    try:
        h, m = map(int, text.split(':'))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError('out of range')
    except ValueError:
        await message.answer('Неверный формат. Введите время как ЧЧ:ММ (например, 13:05):')
        return

    # Build new occurred_at: take date from original, replace time, keep Moscow tz
    try:
        orig = datetime.fromisoformat(original_date_iso).astimezone(_MOSCOW_TZ)
        new_occurred_at = orig.replace(hour=h, minute=m, second=0, microsecond=0)
    except Exception:
        new_occurred_at = datetime.now(_MOSCOW_TZ).replace(hour=h, minute=m, second=0, microsecond=0)

    try:
        updated = await _get_client().update_event(event_id, occurred_at=new_occurred_at)
    except Exception as exc:
        logger.error('update_event (time) failed: %s', exc)
        await message.answer('⚠️ Ошибка при обновлении времени')
        await state.clear()
        return

    await state.clear()

    # Update cached events and re-render summary
    events = await _get_summary_events(state, summary_msg_id)
    events = [updated if e.get('id') == event_id else e for e in events]
    await _update_summary_events(state, summary_msg_id, events)

    # Edit the original summary message
    chat = message.chat
    try:
        await message.bot.edit_message_text(  # type: ignore[union-attr]
            chat_id=chat.id,
            message_id=summary_msg_id,
            text=_format_events({'events': events}),
            reply_markup=event_summary_keyboard(events),
        )
    except Exception as exc:
        logger.warning('edit_message_text failed: %s', exc)
    if data.get('edit_prompt_message_id'):
        try:
            await message.bot.delete_message(  # type: ignore[union-attr]
                chat_id=chat.id, message_id=data['edit_prompt_message_id'],
            )
        except Exception as exc:
            logger.warning('delete prompt message failed: %s', exc)
    await message.delete()


@router.callback_query(F.data.startswith('ev_tp:'))
async def cb_ev_tp(query: CallbackQuery) -> None:
    await _safe_answer(query)
    if query.data is None:
        return
    event_id = query.data.split(':', 1)[1]
    msg = query.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return
    await msg.edit_reply_markup(reply_markup=type_change_keyboard(event_id))


@router.callback_query(F.data.startswith('ev_sub:'))
async def cb_ev_sub(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    if query.data is None:
        return
    parts = query.data.split(':', 2)
    if len(parts) != 3:
        return
    _, event_id, action_id = parts
    msg = query.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return

    if action_id not in ACTION_MAP:
        return
    new_type, preset_payload = ACTION_MAP[action_id]

    try:
        old_event = await _get_client().get_event(event_id)
    except Exception as exc:
        logger.error('get_event failed: %s', exc)
        if query.message:
            await query.message.answer('⚠️ Ошибка')
        return

    old_payload: dict = old_event.get('payload', {})
    merged = dict(preset_payload)
    for field in _COMMON_FIELDS:
        if field in old_payload and field not in merged:
            merged[field] = old_payload[field]

    try:
        updated = await _get_client().update_event(event_id, event_type=new_type, payload=merged)
    except Exception as exc:
        logger.error('update_event (type) failed: %s', exc)
        await query.answer('⚠️ Ошибка при смене типа')
        return

    events = await _get_summary_events(state, msg.message_id)
    events = [updated if e.get('id') == event_id else e for e in events]
    await _update_summary_events(state, msg.message_id, events)

    await msg.edit_text(
        _format_events({'events': events}),
        reply_markup=event_summary_keyboard(events),
    )


@router.callback_query(F.data.startswith('ev_back:'))
async def cb_ev_back(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    msg = query.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return
    events = await _get_summary_events(state, msg.message_id)
    await msg.edit_reply_markup(reply_markup=event_summary_keyboard(events))


@router.callback_query(F.data == 'ev_done')
async def cb_ev_done(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query, 'Готово')
    msg = query.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return
    # Drop cached events for this summary
    data = await state.get_data()
    data.pop(str(msg.message_id), None)
    await state.set_data(data)
    await msg.delete()
