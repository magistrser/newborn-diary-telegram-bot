import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from application.services.action_retry_queue import ActionRetryQueue
from infrastructure.diary_api_client import DiaryApiClient
from infrastructure.logging import configure_logging
from infrastructure.repositories.pending_action_repository import SqlPendingActionsRepository
from settings import settings

logger = logging.getLogger(__name__)


class TelegramAdapterApplicationFactory:
    @staticmethod
    def create_fastapi_app() -> FastAPI:
        configure_logging()
        from infrastructure.endpoints import root_router

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncGenerator[dict, None]:
            from infrastructure.telegram import runner

            logger.info('Application startup started')
            try:
                await runner.start_polling()
            except Exception:
                logger.exception('Application startup failed')
                raise
            logger.info('Application startup completed')
            try:
                yield {}
            finally:
                logger.info('Application shutdown started')
                try:
                    await runner.stop_polling()
                except Exception:
                    logger.exception('Application shutdown failed')
                    raise
                logger.info('Application shutdown completed')

        app = FastAPI(lifespan=lifespan)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['*'],
            allow_methods=['*'],
            allow_headers=['*'],
        )

        @app.middleware('http')
        async def log_http_requests(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if request.url.path in {'/health', '/metrics'}:
                return await call_next(request)

            started_at = perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    'HTTP request failed [method=%s path=%s]',
                    request.method, request.url.path,
                )
                raise

            duration_ms = (perf_counter() - started_at) * 1000
            if response.status_code >= 500:
                logger.error(
                    'HTTP request completed with server error [method=%s path=%s status=%d duration_ms=%.1f]',
                    request.method, request.url.path, response.status_code, duration_ms,
                )
            elif response.status_code >= 400:
                logger.warning(
                    'HTTP request completed with client error [method=%s path=%s status=%d duration_ms=%.1f]',
                    request.method, request.url.path, response.status_code, duration_ms,
                )
            else:
                logger.debug(
                    'HTTP request completed [method=%s path=%s status=%d duration_ms=%.1f]',
                    request.method, request.url.path, response.status_code, duration_ms,
                )
            return response

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
