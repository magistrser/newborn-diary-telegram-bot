"""PostgreSQL-backed aiogram FSM storage.

State and data are stored in separate columns; each update touches only its own
column via ON CONFLICT DO UPDATE.  When set_data({}) is called with state already
NULL the row is deleted, keeping the table free of stale empty entries.
"""
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.models.fsm_state import FsmStateModel

_PK = ['bot_id', 'chat_id', 'user_id', 'destiny']


class SqlFsmStorage(BaseStorage):

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory

    async def set_state(self, key: StorageKey, state: Any = None) -> None:
        state_str: str | None = state.state if isinstance(state, State) else state
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    insert(FsmStateModel)
                    .values(
                        bot_id=key.bot_id,
                        chat_id=key.chat_id,
                        user_id=key.user_id,
                        destiny=key.destiny,
                        state=state_str,
                        data={},
                    )
                    .on_conflict_do_update(
                        index_elements=_PK,
                        set_={'state': state_str},
                    )
                )

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(FsmStateModel).where(
                    FsmStateModel.bot_id == key.bot_id,
                    FsmStateModel.chat_id == key.chat_id,
                    FsmStateModel.user_id == key.user_id,
                    FsmStateModel.destiny == key.destiny,
                )
            )
            row = result.scalar_one_or_none()
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    insert(FsmStateModel)
                    .values(
                        bot_id=key.bot_id,
                        chat_id=key.chat_id,
                        user_id=key.user_id,
                        destiny=key.destiny,
                        state=None,
                        data=data,
                    )
                    .on_conflict_do_update(
                        index_elements=_PK,
                        set_={'data': data},
                    )
                )
                if not data:
                    await session.execute(
                        sa_delete(FsmStateModel).where(
                            FsmStateModel.bot_id == key.bot_id,
                            FsmStateModel.chat_id == key.chat_id,
                            FsmStateModel.user_id == key.user_id,
                            FsmStateModel.destiny == key.destiny,
                            FsmStateModel.state.is_(None),
                        )
                    )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(FsmStateModel).where(
                    FsmStateModel.bot_id == key.bot_id,
                    FsmStateModel.chat_id == key.chat_id,
                    FsmStateModel.user_id == key.user_id,
                    FsmStateModel.destiny == key.destiny,
                )
            )
            row = result.scalar_one_or_none()
            return dict(row.data) if row and row.data else {}

    async def close(self) -> None:
        pass
