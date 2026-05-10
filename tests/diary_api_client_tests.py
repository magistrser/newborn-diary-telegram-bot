"""Tests for DiaryApiClient — mock httpx at the transport level."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.services.diary_api_client import DiaryApiClient
from settings import DiaryApiSettings


def _make_client() -> DiaryApiClient:
    cfg = DiaryApiSettings(base_url='http://test', request_timeout_sec=10)
    return DiaryApiClient(cfg)


def _mock_response(data: dict | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=data or {})
    resp.raise_for_status = MagicMock()
    return resp


def _mock_async_client(response: MagicMock) -> MagicMock:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.patch = AsyncMock(return_value=response)
    mock_client.delete = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


async def test_get_event_issues_correct_get():
    event_data = {'id': 'abc-123', 'type': 'sleep_start', 'payload': {}}
    mock_resp = _mock_response(event_data)
    mock_client = _mock_async_client(mock_resp)

    with patch('httpx.AsyncClient', return_value=mock_client):
        result = await _make_client().get_event('abc-123')

    mock_client.get.assert_called_once_with('http://test/api/v1/events/abc-123')
    assert result == event_data


async def test_update_event_sends_only_provided_fields():
    mock_resp = _mock_response({'id': 'abc-123'})
    mock_client = _mock_async_client(mock_resp)

    occurred_at = datetime(2026, 5, 10, 13, 0, tzinfo=timezone.utc)
    with patch('httpx.AsyncClient', return_value=mock_client):
        await _make_client().update_event('abc-123', occurred_at=occurred_at)

    _, kwargs = mock_client.patch.call_args
    body = kwargs.get('json', {})
    assert 'occurred_at' in body
    assert 'type' not in body
    assert 'payload' not in body


async def test_update_event_sends_type_and_payload():
    mock_resp = _mock_response({'id': 'abc-123'})
    mock_client = _mock_async_client(mock_resp)

    with patch('httpx.AsyncClient', return_value=mock_client):
        await _make_client().update_event(
            'abc-123',
            type='feed_breast',
            payload={'side': 'left'},
        )

    _, kwargs = mock_client.patch.call_args
    body = kwargs.get('json', {})
    assert body['type'] == 'feed_breast'
    assert body['payload'] == {'side': 'left'}
    assert 'occurred_at' not in body


async def test_delete_event_issues_delete():
    mock_resp = _mock_response(status=204)
    mock_client = _mock_async_client(mock_resp)

    with patch('httpx.AsyncClient', return_value=mock_client):
        await _make_client().delete_event('abc-123')

    mock_client.delete.assert_called_once_with('http://test/api/v1/events/abc-123')
