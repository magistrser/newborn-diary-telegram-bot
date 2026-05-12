"""
Telegram message, command, and callback handlers.
All handlers are registered on a single Router defined here.
"""
import html
import logging
import re
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, ReplyParameters, TelegramObject

from application.services.action_retry_queue import ActionRetryQueue, get_retry_queue
from domain.pending_action import PendingAction
from domain.policies import is_allowed, merge_compatible_payload_fields
from domain.quick_actions import ACTION_MAP
from infrastructure.diary_api_client import DiaryApiClient
from infrastructure.telegram.keyboards import event_summary_keyboard, main_keyboard, type_change_keyboard
from settings import settings

_MOSCOW_TZ = ZoneInfo('Europe/Moscow')

logger = logging.getLogger(__name__)

router = Router(name='diary')


class TelegramUpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            author = event.from_user.full_name if event.from_user else None
            user_id = event.from_user.id if event.from_user else None
            logger.debug(
                'Telegram message received [chat_id=%s chat_type=%s author=%r user_id=%s '
                'message_id=%s thread_id=%s has_text=%s]',
                event.chat.id,
                event.chat.type,
                author,
                user_id,
                event.message_id,
                _message_thread_id(event),
                bool(event.text),
            )
        elif isinstance(event, CallbackQuery):
            msg = event.message
            chat_id = msg.chat.id if msg and not isinstance(msg, InaccessibleMessage) else None
            message_id = msg.message_id if msg else None
            logger.debug(
                'Telegram callback received [chat_id=%s from_user_id=%s message_id=%s data=%r]',
                chat_id,
                event.from_user.id,
                message_id,
                event.data,
            )

        return await handler(event, data)


router.message.outer_middleware(TelegramUpdateLoggingMiddleware())
router.callback_query.outer_middleware(TelegramUpdateLoggingMiddleware())


class AskState(StatesGroup):
    waiting_for_question = State()


class EditState(StatesGroup):
    waiting_for_new_time = State()


def _is_allowed(chat_id: int, author: str | None) -> bool:
    return is_allowed(
        chat_id=chat_id,
        author=author,
        allowed_chat_ids=settings.telegram.allowed_chat_ids,
        allowed_authors=settings.telegram.allowed_authors,
    )


def _get_client() -> DiaryApiClient:
    return DiaryApiClient(settings.diary_api)


def _get_retry_queue() -> ActionRetryQueue:
    return get_retry_queue()


def _configured_topic_id(name: str) -> int | None:
    value = getattr(settings.telegram, name, None)
    return value if isinstance(value, int) else None


def _message_thread_id(message: Message) -> int | None:
    value = getattr(message, 'message_thread_id', None)
    return value if isinstance(value, int) else None


def _message_user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def _topic_matches(message: Message, topic_id: int | None) -> bool:
    return topic_id is None or _message_thread_id(message) == topic_id


def _is_event_topic(message: Message) -> bool:
    return _topic_matches(message, _configured_topic_id('event_topic_id'))


def _is_question_topic(message: Message) -> bool:
    return _topic_matches(message, _configured_topic_id('question_topic_id'))


def _has_configured_question_topic() -> bool:
    return _configured_topic_id('question_topic_id') is not None


def _question_text(text: str) -> str:
    return text[1:].strip() if text.startswith('?') else text.strip()


async def _answer_in_question_topic(message: Message, text: str) -> None:
    topic_id = _configured_topic_id('question_topic_id')
    if topic_id is None or _message_thread_id(message) == topic_id:
        await message.answer(text)
        return

    await message.bot.send_message(  # type: ignore[union-attr]
        chat_id=message.chat.id,
        message_thread_id=topic_id,
        text=text,
    )


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


def _create_event_result(action: PendingAction, result: dict[str, Any]) -> dict[str, Any]:
    event = result.get('event')
    if isinstance(event, dict):
        return event
    if result.get('type') or result.get('occurred_at') or result.get('payload'):
        return result
    return {
        'type': action.event_type or '',
        'occurred_at': action.occurred_at or '',
        'payload': action.payload or {},
    }


def _format_retry_success(action: PendingAction, result: dict[str, Any]) -> str:
    if action.action_type == 'parse_text':
        return '🔁 Повторная попытка успешна.\n' + _format_events(result)
    if action.action_type == 'create_event':
        return '✅ Сохранил после повтора:\n' + _format_event(_create_event_result(action, result))
    return '✅ Повторная попытка успешна'


def _retry_reply_parameters(action: PendingAction) -> ReplyParameters | None:
    if not action.source_message_id:
        return None
    try:
        message_id = int(action.source_message_id)
    except ValueError:
        return None
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True)


async def _store_retry_summary_events(
    storage: BaseStorage | None,
    bot: Bot,
    action: PendingAction,
    summary_message_id: int,
    events: list[dict[str, Any]],
) -> bool:
    if storage is None or action.source_chat_id is None or action.source_user_id is None:
        logger.warning(
            'Cannot attach retry confirmation keyboard without FSM metadata '
            '[id=%s action_type=%s has_storage=%s chat_id=%s user_id=%s]',
            action.id, action.action_type, storage is not None, action.source_chat_id, action.source_user_id,
        )
        return False

    try:
        key = StorageKey(
            bot_id=bot.id,
            chat_id=action.source_chat_id,
            user_id=action.source_user_id,
        )
        data = await storage.get_data(key)
        data[str(summary_message_id)] = events
        await storage.set_data(key, data)
    except Exception:
        logger.warning(
            'Failed to store retry confirmation events [id=%s message_id=%s]',
            action.id, summary_message_id,
            exc_info=True,
        )
        return False
    return True


async def notify_retry_success(
    bot: Bot,
    storage: BaseStorage | None,
    action: PendingAction,
    result: dict[str, Any],
) -> None:
    if action.source_chat_id is None:
        logger.debug(
            'Skipping retry success Telegram notification without chat id [id=%s action_type=%s]',
            action.id, action.action_type,
        )
        return

    sent = await bot.send_message(
        chat_id=action.source_chat_id,
        text=_format_retry_success(action, result),
        reply_parameters=_retry_reply_parameters(action),
    )
    events = result.get('events', []) if action.action_type == 'parse_text' else []
    if not events or not sent:
        return

    if await _store_retry_summary_events(storage, bot, action, sent.message_id, events):
        try:
            await bot.edit_message_reply_markup(
                chat_id=action.source_chat_id,
                message_id=sent.message_id,
                reply_markup=event_summary_keyboard(events),
            )
        except Exception:
            logger.warning(
                'Failed to attach retry confirmation keyboard [id=%s message_id=%s]',
                action.id, sent.message_id,
                exc_info=True,
            )


async def _safe_answer(query: CallbackQuery, text: str = '') -> None:
    try:
        await query.answer(text)
    except Exception:
        logger.warning('query.answer failed (stale callback?)', exc_info=True)


# ── Commands ─────────────────────────────────────────────────────────────────

@router.message(Command('start'))
@router.message(Command('menu'))
async def cmd_menu(message: Message) -> None:
    logger.debug(
        'Sending menu [chat_id=%s message_id=%s thread_id=%s]',
        message.chat.id, message.message_id, _message_thread_id(message),
    )
    await message.answer('Выберите действие:', reply_markup=main_keyboard())


@router.message(Command('ask'))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    if not _is_question_topic(message):
        logger.debug(
            'Ignoring /ask outside question topic [chat_id=%s message_id=%s thread_id=%s]',
            message.chat.id, message.message_id, _message_thread_id(message),
        )
        return

    text = message.text or ''
    question = text.partition(' ')[2].strip()
    if question:
        await _handle_question(message, question)
    else:
        await state.set_state(AskState.waiting_for_question)
        await _answer_in_question_topic(message, 'Задайте вопрос:')


# ── Question mode FSM ─────────────────────────────────────────────────────────

@router.message(AskState.waiting_for_question)
async def handle_question_in_state(message: Message, state: FSMContext) -> None:
    logger.debug(
        'Handling message while waiting for question [chat_id=%s message_id=%s thread_id=%s '
        'is_event_topic=%s is_question_topic=%s]',
        message.chat.id,
        message.message_id,
        _message_thread_id(message),
        _is_event_topic(message),
        _is_question_topic(message),
    )
    if not _is_question_topic(message):
        if _is_event_topic(message):
            await _handle_event_text(message, state)
        else:
            logger.debug(
                'Ignoring waiting-for-question message outside configured topics '
                '[chat_id=%s message_id=%s thread_id=%s]',
                message.chat.id, message.message_id, _message_thread_id(message),
            )
        return

    await state.clear()
    await _handle_question(message, _question_text(message.text or ''))


async def _handle_question(message: Message, question: str) -> None:
    try:
        result = await _get_client().ask(question)
        await _answer_in_question_topic(message, html.escape(result.get('answer', '(нет ответа)')))
        logger.debug(
            'Question answered [chat_id=%s message_id=%s thread_id=%s question_len=%d]',
            message.chat.id, message.message_id, _message_thread_id(message), len(question),
        )
    except Exception:
        logger.exception(
            'ask failed [chat_id=%s message_id=%s thread_id=%s question_len=%d]',
            message.chat.id, message.message_id, _message_thread_id(message), len(question),
        )
        await _answer_in_question_topic(message, '⚠️ Ошибка при обращении к дневнику. Попробуйте позже.')


# ── Free-form text ────────────────────────────────────────────────────────────

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    author = message.from_user.full_name if message.from_user else None
    text = message.text or ''

    logger.debug(
        'Handling Telegram text [chat_id=%s author=%r message_id=%s thread_id=%s text_len=%d '
        'is_event_topic=%s is_question_topic=%s]',
        chat_id,
        author,
        message.message_id,
        _message_thread_id(message),
        len(text),
        _is_event_topic(message),
        _is_question_topic(message),
    )

    if not _is_allowed(chat_id, author):
        logger.debug(
            'Ignoring message from disallowed chat or author [chat_id=%s author=%r message_id=%s thread_id=%s]',
            chat_id, author, message.message_id, _message_thread_id(message),
        )
        return

    if _has_configured_question_topic() and _is_question_topic(message):
        await _handle_question(message, _question_text(text))
        return

    # Route to ask if starts with ? in legacy no-dedicated-topic mode.
    if text.startswith('?'):
        if not _is_question_topic(message):
            logger.debug(
                'Ignoring question outside question topic [chat_id=%s message_id=%s thread_id=%s]',
                chat_id, message.message_id, _message_thread_id(message),
            )
            return
        await _handle_question(message, _question_text(text))
        return

    if not _is_event_topic(message):
        logger.debug(
            'Ignoring event text outside event topic [chat_id=%s message_id=%s thread_id=%s]',
            chat_id, message.message_id, _message_thread_id(message),
        )
        return

    await _handle_event_text(message, state)


async def _handle_event_text(message: Message, state: FSMContext) -> None:
    text = message.text or ''
    chat_id = message.chat.id
    occurred_at = message.date.replace(tzinfo=timezone.utc) if message.date else datetime.now(timezone.utc)
    msg_id = str(message.message_id)
    user_id = _message_user_id(message)

    try:
        logger.debug(
            'Sending Telegram message to diary API for parsing [chat_id=%s message_id=%s thread_id=%s '
            'text_len=%d timeout_sec=%d]',
            chat_id,
            message.message_id,
            _message_thread_id(message),
            len(text),
            settings.diary_api.request_timeout_sec,
        )
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
        logger.debug(
            'Parsed Telegram message [chat_id=%s message_id=%s thread_id=%s events_count=%d]',
            chat_id, message.message_id, _message_thread_id(message), len(events),
        )
    except Exception:
        logger.exception(
            'parse_text failed [chat_id=%s message_id=%s thread_id=%s text_len=%d]',
            chat_id, message.message_id, _message_thread_id(message), len(text),
        )
        await _get_retry_queue().enqueue_parse_text(
            text=text,
            occurred_at=occurred_at,
            source_type='telegram_live',
            source_message_id=msg_id,
            source_chat_id=chat_id,
            source_user_id=user_id,
        )
        await message.reply('⚠️ Не удалось сохранить сообщение — повторю попытку автоматически.')


# ── Inline keyboard callbacks ─────────────────────────────────────────────────

@router.callback_query(F.data == 'ask_mode')
async def cb_ask_mode(query: CallbackQuery, state: FSMContext) -> None:
    await _safe_answer(query)
    await state.set_state(AskState.waiting_for_question)
    if query.message and not isinstance(query.message, InaccessibleMessage):
        await _answer_in_question_topic(query.message, 'Задайте вопрос:')


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
        logger.debug('Quick action saved [action_id=%s event_type=%s]', action_id, event_type)
    except Exception:
        logger.exception('quick_action failed [action_id=%s event_type=%s]', action_id, event_type)
        source_chat_id = None
        source_message_id = None
        if query.message and not isinstance(query.message, InaccessibleMessage):
            source_chat_id = query.message.chat.id
            source_message_id = str(query.message.message_id)
        await _get_retry_queue().enqueue_create_event(
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            source_type='telegram_quick_action',
            source_message_id=source_message_id,
            source_chat_id=source_chat_id,
            source_user_id=query.from_user.id,
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
    except Exception:
        logger.exception(
            'delete_event failed [event_id=%s chat_id=%s message_id=%s]',
            event_id, msg.chat.id, msg.message_id,
        )
        if msg:
            await msg.answer('⚠️ Ошибка при удалении')
        return

    events = await _get_summary_events(state, msg.message_id)
    events = [e for e in events if e.get('id') != event_id]

    if not events:
        data = await state.get_data()
        data.pop(str(msg.message_id), None)
        await state.set_data(data)
        await msg.delete()
    else:
        await _update_summary_events(state, msg.message_id, events)
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
    except Exception:
        logger.exception(
            'update_event time failed [event_id=%s chat_id=%s message_id=%s]',
            event_id, message.chat.id, message.message_id,
        )
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
    except Exception:
        logger.warning(
            'edit_message_text failed [chat_id=%s summary_message_id=%s]',
            chat.id, summary_msg_id,
            exc_info=True,
        )
    if data.get('edit_prompt_message_id'):
        try:
            await message.bot.delete_message(  # type: ignore[union-attr]
                chat_id=chat.id, message_id=data['edit_prompt_message_id'],
            )
        except Exception:
            logger.warning(
                'delete prompt message failed [chat_id=%s prompt_message_id=%s]',
                chat.id, data['edit_prompt_message_id'],
                exc_info=True,
            )
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
    except Exception:
        logger.exception('get_event failed [event_id=%s]', event_id)
        if query.message:
            await query.message.answer('⚠️ Ошибка')
        return

    old_payload: dict = old_event.get('payload', {})
    merged = merge_compatible_payload_fields(preset_payload, old_payload)

    try:
        updated = await _get_client().update_event(event_id, event_type=new_type, payload=merged)
    except Exception:
        logger.exception('update_event type failed [event_id=%s new_type=%s]', event_id, new_type)
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
