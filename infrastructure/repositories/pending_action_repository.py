from sqlalchemy import delete as sa_delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from application.services.action_retry_queue import PendingAction
from infrastructure.models.base import Base
from infrastructure.models.pending_action import PendingActionModel


def _to_domain(row: PendingActionModel) -> PendingAction:
    return PendingAction(
        id=row.id,
        action_type=row.action_type,
        created_at=row.created_at,
        attempt_count=row.attempt_count,
        text=row.text,
        occurred_at=row.occurred_at,
        source_type=row.source_type,
        source_message_id=row.source_message_id,
        source_chat_id=row.source_chat_id,
        event_type=row.event_type,
        payload=row.payload,
    )


class SqlPendingActionsRepository:

    def __init__(self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._engine = engine
        self._session_factory = session_factory

    async def setup(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def load_all(self) -> list[PendingAction]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PendingActionModel).order_by(PendingActionModel.created_at)
            )
            return [_to_domain(row) for row in result.scalars()]

    async def upsert(self, action: PendingAction) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    insert(PendingActionModel)
                    .values(
                        id=action.id,
                        action_type=action.action_type,
                        created_at=action.created_at,
                        attempt_count=action.attempt_count,
                        text=action.text,
                        occurred_at=action.occurred_at,
                        source_type=action.source_type,
                        source_message_id=action.source_message_id,
                        source_chat_id=action.source_chat_id,
                        event_type=action.event_type,
                        payload=action.payload,
                    )
                    .on_conflict_do_update(
                        index_elements=['id'],
                        set_={'attempt_count': action.attempt_count},
                    )
                )
                await session.execute(stmt)

    async def delete(self, action_id: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    sa_delete(PendingActionModel).where(PendingActionModel.id == action_id)
                )
