from os import environ
from pathlib import Path

from pydantic import BaseModel, Field
from yaml import safe_load


class TelegramSettings(BaseModel):
    bot_token: str = Field(...)
    allowed_chat_ids: list[int] = Field(default_factory=list)
    allowed_authors: list[str] = Field(default_factory=list)


class DiaryApiSettings(BaseModel):
    base_url: str = Field(...)
    request_timeout_sec: int = Field(default=660)


class Settings(BaseModel):
    telegram: TelegramSettings = Field(...)
    diary_api: DiaryApiSettings = Field(...)


def get_settings() -> Settings:
    root_dir = Path(__file__).parent
    environment = environ.get('ENVIRONMENT')

    match environment:
        case 'DEVELOPMENT' | 'TEST' | None:
            settings_path = root_dir / 'settings.dev.yml'
        case 'PRODUCTION':
            settings_path = root_dir / 'settings.yml'
        case invalid:
            raise ValueError(f'Failed to initialize settings. Invalid ENVIRONMENT variable: {invalid}')

    with open(settings_path, 'r', encoding='utf-8') as settings_file:
        return Settings.model_validate(safe_load(settings_file))


settings = get_settings()
