from os import environ
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from yaml import safe_load


class TelegramSettings(BaseModel):
    bot_token: str = Field(...)
    allowed_chat_ids: list[int] = Field(default_factory=list)
    allowed_authors: list[str] = Field(default_factory=list)


class DiaryApiSettings(BaseModel):
    base_url: str = Field(...)
    request_timeout_sec: int = Field(default=660)


class PostgresSettings(BaseModel):
    host: str = Field(...)
    port: int = Field(...)
    db_name: str = Field(...)
    user: str = Field(...)
    password: str = Field(...)
    pool_size: int = Field(default=5)

    def get_async_url(self) -> str:
        return f'postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}'

    def create_engine(self) -> AsyncEngine:
        return create_async_engine(
            url=self.get_async_url(),
            pool_pre_ping=True,
            pool_size=self.pool_size,
            echo=False,
        )


class RetrySettings(BaseModel):
    interval_min: int = Field(default=10)


class Settings(BaseModel):
    telegram: TelegramSettings = Field(...)
    diary_api: DiaryApiSettings = Field(...)
    postgres: PostgresSettings = Field(...)
    retry: RetrySettings = Field(default_factory=RetrySettings)


def get_settings() -> Settings:
    root_dir = Path(__file__).parent
    environment = environ.get('ENVIRONMENT')

    match environment:
        case 'DEVELOPMENT' | None:
            settings_path = root_dir / 'settings.dev.yml'
        case 'TEST':
            settings_path = root_dir / 'settings.test.yml'
        case 'PRODUCTION':
            settings_path = root_dir / 'settings.yml'
        case invalid:
            raise ValueError(f'Failed to initialize settings. Invalid ENVIRONMENT variable: {invalid}')

    with open(settings_path, 'r', encoding='utf-8') as settings_file:
        return Settings.model_validate(safe_load(settings_file))


settings = get_settings()
