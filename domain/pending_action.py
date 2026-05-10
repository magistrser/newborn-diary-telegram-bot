import uuid
from typing import Any

from pydantic import BaseModel, Field


class PendingAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str
    created_at: str
    attempt_count: int = 0
    text: str | None = None
    occurred_at: str | None = None
    source_type: str | None = None
    source_message_id: str | None = None
    source_chat_id: int | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None
