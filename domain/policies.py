from typing import Any


COMMON_PAYLOAD_FIELDS = {'duration_min'}


def is_allowed(
    *,
    chat_id: int,
    author: str | None,
    allowed_chat_ids: list[int],
    allowed_authors: list[str],
) -> bool:
    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        return False
    if allowed_authors and author and author not in allowed_authors:
        return False
    return True


def merge_compatible_payload_fields(
    preset_payload: dict[str, Any],
    old_payload: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(preset_payload)
    for field in COMMON_PAYLOAD_FIELDS:
        if field in old_payload and field not in merged:
            merged[field] = old_payload[field]
    return merged
