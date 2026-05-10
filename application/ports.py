from datetime import datetime
from typing import Any, Protocol

from domain.pending_action import PendingAction


class DiaryApiPort(Protocol):
    async def parse_text(
        self,
        text: str,
        occurred_at: datetime,
        source_type: str = 'telegram_live',
        source_message_id: str | None = None,
        source_chat_id: int | None = None,
    ) -> dict[str, Any]:
        ...

    async def create_event(
        self,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        source_type: str = 'telegram_quick_action',
    ) -> dict[str, Any]:
        ...

    async def get_event(self, event_id: str) -> dict[str, Any]:
        ...

    async def update_event(
        self,
        event_id: str,
        *,
        occurred_at: datetime | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    async def delete_event(self, event_id: str) -> None:
        ...

    async def ask(self, question: str) -> dict[str, Any]:
        ...


class PendingActionsRepositoryPort(Protocol):
    async def setup(self) -> None:
        ...

    async def load_all(self) -> list[PendingAction]:
        ...

    async def upsert(self, action: PendingAction) -> None:
        ...

    async def delete(self, action_id: str) -> None:
        ...
