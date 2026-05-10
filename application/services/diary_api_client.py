"""Async HTTP client for the diary_api service."""
from datetime import datetime, timezone
from typing import Any

import httpx

from settings import DiaryApiSettings


class DiaryApiClient:

    def __init__(self, api_settings: DiaryApiSettings) -> None:
        self._base_url = api_settings.base_url.rstrip('/')
        self._timeout = api_settings.request_timeout_sec

    async def parse_text(
        self,
        text: str,
        occurred_at: datetime,
        source_type: str = 'telegram_live',
        source_message_id: str | None = None,
        source_chat_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'text': text,
            'occurred_at': occurred_at.isoformat(),
            'source_type': source_type,
        }
        if source_message_id is not None:
            payload['source_message_id'] = source_message_id
        if source_chat_id is not None:
            payload['source_chat_id'] = source_chat_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f'{self._base_url}/api/v1/events/from-text',
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_event(
        self,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        source_type: str = 'telegram_quick_action',
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            'type': event_type,
            'occurred_at': occurred_at.isoformat(),
            'payload': payload,
            'source_type': source_type,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f'{self._base_url}/api/v1/events',
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_event(self, event_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f'{self._base_url}/api/v1/events/{event_id}')
            resp.raise_for_status()
            return resp.json()

    async def update_event(
        self,
        event_id: str,
        *,
        occurred_at: datetime | None = None,
        type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if occurred_at is not None:
            body['occurred_at'] = occurred_at.isoformat()
        if type is not None:
            body['type'] = type
        if payload is not None:
            body['payload'] = payload
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.patch(
                f'{self._base_url}/api/v1/events/{event_id}',
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def delete_event(self, event_id: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.delete(f'{self._base_url}/api/v1/events/{event_id}')
            resp.raise_for_status()

    async def ask(self, question: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f'{self._base_url}/api/v1/ask',
                json={'question': question},
            )
            resp.raise_for_status()
            return resp.json()
