import os
from typing import Optional
from pydantic import validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Конфигурация бота с валидацией"""
    
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
    
    @validator('telegram_bot_token')
    def validate_telegram_token(cls, v):
        if not v or len(v) < 10:
            raise ValueError('TELEGRAM_BOT_TOKEN должен быть валидным токеном')
        return v
    
    @validator('pollinations_token')
    def validate_pollinations_token(cls, v):
        if not v or len(v) < 10:
            raise ValueError('POLLINATIONS_TOKEN должен быть валидным токеном')
        return v
    
    @validator('context_limit')
    def validate_context_limit(cls, v):
        if v < 1 or v > 100:
            raise ValueError('CONTEXT_LIMIT должен быть между 1 и 100')
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Глобальный экземпляр настроек
settings = Settings()
