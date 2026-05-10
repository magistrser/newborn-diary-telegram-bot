from typing import Any


QUICK_ACTIONS: list[tuple[str, str, str | None, dict[str, Any] | None]] = [
    ('feed_left', '🍼 Левая', 'feed_breast', {'side': 'left'}),
    ('feed_right', '🍼 Правая', 'feed_breast', {'side': 'right'}),
    ('feed_bottle_formula', '🍶 Смесь', 'feed_bottle', {'contents': 'formula'}),
    ('feed_bottle_expr', '🍶 Сцеженное', 'feed_bottle', {'contents': 'expressed'}),
    ('pump', '🥛 Сцедила', 'pump', {}),
    ('diaper_pee', '💧 Пописал', 'diaper', {'kind': 'pee'}),
    ('diaper_poo', '💩 Покакал', 'diaper', {'kind': 'poo'}),
    ('diaper_unknown', '🚼 Подгузник', 'diaper', {'kind': 'unknown'}),
    ('sleep_start', '😴 Заснул', 'sleep_start', {}),
    ('sleep_end', '🌅 Проснулся', 'sleep_end', {}),
    ('bath', '🛁 Купание', 'bath', {}),
    ('tummy_time', '🤸 На животике', 'tummy_time', {}),
    ('spit_up_small', '🤧 Срыгнул чуть', 'spit_up', {'volume': 'small'}),
    ('spit_up_large', '🤮 Срыгнул много', 'spit_up', {'volume': 'large'}),
    ('gas', '💨 Газики', 'gas', {}),
    ('vitamin_d', '💊 Витамин Д', 'medication', {'name': 'Витамин Д'}),
    ('ask_mode', '❓ Спросить', None, None),
]

ACTION_MAP: dict[str, tuple[str, dict[str, Any]]] = {
    action_id: (event_type, payload)
    for action_id, _, event_type, payload in QUICK_ACTIONS
    if event_type is not None and payload is not None
}
