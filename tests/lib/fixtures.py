from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from application.services.action_retry_queue import ActionRetryQueue, set_retry_queue
from infrastructure.models import Base
from settings import DiaryApiSettings


class _InMemoryRepo:
    """Minimal in-memory repo for the fixture-level queue."""

    def __init__(self) -> None:
        self._store: dict = {}

    async def setup(self) -> None:
        pass

    async def load_all(self) -> list:
        return []

    async def upsert(self, action: Any) -> None:
        self._store[action.id] = action

    async def delete(self, action_id: str) -> None:
        self._store.pop(action_id, None)


@pytest.fixture
def application_client() -> Generator[TestClient, None, None]:
    from main import app

    # Wire up a no-op retry queue so handlers can call get_retry_queue()
    _api_settings = DiaryApiSettings(base_url='http://test', request_timeout_sec=10)
    queue = ActionRetryQueue(repo=_InMemoryRepo(), diary_api_settings=_api_settings)
    set_retry_queue(queue)

    with patch('main.start_polling', new_callable=AsyncMock), \
         patch('main.stop_polling', new_callable=AsyncMock):
        with TestClient(app) as client:
            yield client


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    from settings import settings
    engine: AsyncEngine = create_async_engine(settings.postgres.get_async_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
    await engine.dispose()
