import os
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация бота с валидацией (Pydantic v2)"""

    # Telegram Bot Token
    telegram_bot_token: str

    # Pollinations API Token
    pollinations_token: str

    # Контекст и лимиты
    context_limit: int = 20
    max_message_length: int = 4000
    max_voice_size_mb: int = 50
    max_image_size_mb: int = 10

    # Таймауты (в секундах)
    api_timeout: int = 60
    voice_processing_timeout: int = 30
    typing_interval: int = 5

    # Rate limiting
    min_request_interval: float = 2.0
    max_requests_per_minute: int = 30

    # Логирование
    log_level: str = "INFO"

    # Конфигурация загрузки из окружения
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

    @field_validator('telegram_bot_token')
    @classmethod
    def validate_telegram_token(cls, v: str) -> str:
        if not v or len(v) < 10:
            raise ValueError('TELEGRAM_BOT_TOKEN должен быть валидным токеном')
        return v

    @field_validator('pollinations_token')
    @classmethod
    def validate_pollinations_token(cls, v: str) -> str:
        if not v or len(v) < 10:
            raise ValueError('POLLINATIONS_TOKEN должен быть валидным токеном')
        return v

    @field_validator('context_limit')
    @classmethod
    def validate_context_limit(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError('CONTEXT_LIMIT должен быть между 1 и 100')
        return v


# Глобальный экземпляр настроек
settings = Settings()
