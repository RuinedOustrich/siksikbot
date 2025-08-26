import os
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
    # max_message_length убран - Telegram сам ограничивает длину сообщений
    max_voice_size_mb: int = 50
    max_image_size_mb: int = 10

    # Таймауты (в секундах)
    api_timeout: int = 60
    voice_processing_timeout: int = 30
    typing_interval: int = 5

    # Rate limiting
    min_request_interval: float = 2.0
    max_requests_per_minute: int = 30

    # Автоматический анализ сгенерированных изображений
    auto_analyze_generated_images: bool = True

    # Предустановленные размеры изображений
    image_size_presets: dict = {
        "square": {"width": 1024, "height": 1024, "name": "Квадрат", "emoji": "📐"},
        "portrait": {"width": 768, "height": 1024, "name": "Портрет", "emoji": "📄"},
        "landscape": {"width": 1024, "height": 768, "name": "Пейзаж", "emoji": "🖼️"},
        "wide": {"width": 1280, "height": 720, "name": "Широкий", "emoji": "📺"},
        "wallpaper": {"width": 1920, "height": 1080, "name": "Обои", "emoji": "💻"},
        "mobile": {"width": 1080, "height": 1920, "name": "Мобильный", "emoji": "📱"},
        "story": {"width": 1080, "height": 1920, "name": "Сторис", "emoji": "📲"},
        "post": {"width": 1080, "height": 1080, "name": "Пост", "emoji": "📮"}
    }

    # Предустановленные стили изображений
    image_style_presets: dict = {
        "realism": {"name": "Реализм", "emoji": "🖼️", "prompt": "photorealistic, detailed, high quality"},
        "anime": {"name": "Аниме", "emoji": "🎭", "prompt": "anime style, manga style, japanese animation"},
        "cartoon": {"name": "Мультфильм", "emoji": "🎪", "prompt": "cartoon style, animated, colorful"},
        "watercolor": {"name": "Акварель", "emoji": "🖌️", "prompt": "watercolor painting, soft colors, artistic"},
        "fantasy": {"name": "Фэнтези", "emoji": "✨", "prompt": "fantasy art, magical, mystical, enchanted"},
        "retro": {"name": "Ретро", "emoji": "🏛️", "prompt": "retro style, vintage, classic"},
        "cyberpunk": {"name": "Киберпанк", "emoji": "🤖", "prompt": "cyberpunk style, neon lights, futuristic"},
        "minimalism": {"name": "Минимализм", "emoji": "🌸", "prompt": "minimalist style, simple, clean, elegant"}
    }

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



    @field_validator('max_voice_size_mb')
    @classmethod
    def validate_max_voice_size(cls, v: int) -> int:
        if v < 1 or v > 200:
            raise ValueError('MAX_VOICE_SIZE_MB должен быть между 1 и 200')
        return v

    @field_validator('max_image_size_mb')
    @classmethod
    def validate_max_image_size(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError('MAX_IMAGE_SIZE_MB должен быть между 1 и 50')
        return v

    @field_validator('api_timeout')
    @classmethod
    def validate_api_timeout(cls, v: int) -> int:
        if v < 10 or v > 300:
            raise ValueError('API_TIMEOUT должен быть между 10 и 300 секунд')
        return v

    @field_validator('min_request_interval')
    @classmethod
    def validate_min_request_interval(cls, v: float) -> float:
        if v < 0.1 or v > 10.0:
            raise ValueError('MIN_REQUEST_INTERVAL должен быть между 0.1 и 10.0 секунд')
        return v

    @field_validator('max_requests_per_minute')
    @classmethod
    def validate_max_requests_per_minute(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError('MAX_REQUESTS_PER_MINUTE должен быть между 1 и 100')
        return v


# Глобальный экземпляр настроек
settings = Settings()
