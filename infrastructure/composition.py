from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from application.services.action_retry_queue import ActionRetryQueue
from infrastructure.diary_api_client import DiaryApiClient
from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository
from settings import settings


class TelegramAdapterApplicationFactory:
    @staticmethod
    def create_fastapi_app() -> FastAPI:
        from infrastructure.endpoints import root_router

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncGenerator[dict, None]:
            from infrastructure.telegram import runner

            await runner.start_polling()
            try:
                yield {}
            finally:
                await runner.stop_polling()

        app = FastAPI(lifespan=lifespan)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['*'],
            allow_methods=['*'],
            allow_headers=['*'],
        )
        app.include_router(root_router)
        return app

    @staticmethod
    def diary_api_client() -> DiaryApiClient:
        return DiaryApiClient(settings.diary_api)

    @staticmethod
    def action_retry_queue(
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ActionRetryQueue:
        repo = SqlPendingActionsRepository(engine, session_factory)
        return ActionRetryQueue(
            repo=repo,
            diary_api=TelegramAdapterApplicationFactory.diary_api_client(),
            retry_interval_min=settings.retry.interval_min,
        )
