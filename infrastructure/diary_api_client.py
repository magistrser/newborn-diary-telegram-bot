"""Async HTTP client for the diary_api service."""
import logging
from contextlib import suppress
from datetime import datetime
from time import perf_counter
from typing import Any

import httpx

from settings import DiaryApiSettings

logger = logging.getLogger(__name__)
_ERROR_BODY_LOG_LIMIT = 500


def _response_body_excerpt(response: httpx.Response) -> str:
    with suppress(Exception):
        return response.text[:_ERROR_BODY_LOG_LIMIT]
    return ''


def _log_http_status_error(method: str, path: str, started_at: float, exc: httpx.HTTPStatusError) -> None:
    logger.warning(
        'Diary API returned an error [method=%s path=%s status=%d duration_ms=%.1f body=%r]',
        method, path, exc.response.status_code, _duration_ms(started_at), _response_body_excerpt(exc.response),
    )


def _log_request_error(method: str, path: str, started_at: float, exc: httpx.RequestError) -> None:
    logger.warning(
        'Diary API request failed [method=%s path=%s duration_ms=%.1f error=%s]',
        method, path, _duration_ms(started_at), exc,
    )


def _duration_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000


def _log_success(method: str, path: str, started_at: float, status_code: int) -> None:
    logger.info(
        'Diary API request completed [method=%s path=%s status=%d duration_ms=%.1f]',
        method, path, status_code, _duration_ms(started_at),
    )


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

        path = '/api/v1/events/from-text'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f'{self._base_url}{path}', json=payload)
                resp.raise_for_status()
                _log_success('POST', path, started_at, resp.status_code)
                return resp.json()
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('POST', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('POST', path, started_at, exc)
            raise

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
        path = '/api/v1/events'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f'{self._base_url}{path}', json=body)
                resp.raise_for_status()
                _log_success('POST', path, started_at, resp.status_code)
                return resp.json()
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('POST', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('POST', path, started_at, exc)
            raise

    async def get_event(self, event_id: str) -> dict[str, Any]:
        path = f'/api/v1/events/{event_id}'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f'{self._base_url}{path}')
                resp.raise_for_status()
                _log_success('GET', path, started_at, resp.status_code)
                return resp.json()
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('GET', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('GET', path, started_at, exc)
            raise

    async def update_event(
        self,
        event_id: str,
        *,
        occurred_at: datetime | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if occurred_at is not None:
            body['occurred_at'] = occurred_at.isoformat()
        if event_type is not None:
            body['type'] = event_type
        if payload is not None:
            body['payload'] = payload
        path = f'/api/v1/events/{event_id}'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.patch(f'{self._base_url}{path}', json=body)
                resp.raise_for_status()
                _log_success('PATCH', path, started_at, resp.status_code)
                return resp.json()
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('PATCH', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('PATCH', path, started_at, exc)
            raise

    async def delete_event(self, event_id: str) -> None:
        path = f'/api/v1/events/{event_id}'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.delete(f'{self._base_url}{path}')
                resp.raise_for_status()
                _log_success('DELETE', path, started_at, resp.status_code)
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('DELETE', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('DELETE', path, started_at, exc)
            raise

    async def ask(self, question: str) -> dict[str, Any]:
        path = '/api/v1/ask'
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f'{self._base_url}{path}', json={'question': question})
                resp.raise_for_status()
                _log_success('POST', path, started_at, resp.status_code)
                return resp.json()
        except httpx.HTTPStatusError as exc:
            _log_http_status_error('POST', path, started_at, exc)
            raise
        except httpx.RequestError as exc:
            _log_request_error('POST', path, started_at, exc)
            raise
