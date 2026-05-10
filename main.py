from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from infrastructure.endpoints import root_router
from infrastructure.telegram.runner import start_polling, stop_polling


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[dict]:
    await start_polling()
    yield {}
    await stop_polling()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(root_router)
