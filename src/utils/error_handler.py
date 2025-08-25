import logging
import traceback
from typing import Optional, Dict, Any
from telegram import Update
from telegram.ext import CallbackContext
from config.settings import settings

logger = logging.getLogger(__name__)


class BotError(Exception):
    """Базовый класс для ошибок бота"""
    def __init__(self, message: str, user_friendly: str = None, context: Dict[str, Any] = None):
        super().__init__(message)
        self.user_friendly = user_friendly or "Произошла ошибка. Попробуйте позже."
        self.context = context or {}


class APIError(BotError):
    """Ошибка API"""
    pass


class RateLimitError(BotError):
    """Ошибка превышения лимита запросов"""
    pass


class ValidationError(BotError):
    """Ошибка валидации данных"""
    pass


async def handle_error(update: Update, context: CallbackContext) -> None:
    """Централизованный обработчик ошибок"""
    try:
        # Логируем ошибку
        logger.error(f"Exception while handling an update: {context.error}")
        
        # Получаем информацию об ошибке
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = ''.join(tb_list)
        
        # Создаем сообщение для логирования
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        message = (
            f'An exception was raised while handling an update\n'
            f'update = {update_str}\n'
            f'error = {tb_string}'
        )
        
        # Логируем детали
        logger.error(message)
        
        # Определяем тип ошибки и отправляем пользователю понятное сообщение
        error_message = get_user_friendly_error(context.error)
        
        # Отправляем сообщение пользователю
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(error_message)
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение об ошибке: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка в обработчике ошибок: {e}")


def get_user_friendly_error(error: Exception) -> str:
    """Возвращает понятное пользователю сообщение об ошибке"""
    
    if isinstance(error, BotError):
        return error.user_friendly
    
    # Обработка специфических ошибок
    error_str = str(error).lower()
    
    if "timeout" in error_str or "timed out" in error_str:
        return "⏰ Превышено время ожидания ответа. Попробуйте позже."
    
    elif "rate limit" in error_str or "too many requests" in error_str:
        return "🚫 Слишком много запросов. Подождите немного."
    
    elif "unauthorized" in error_str or "invalid token" in error_str:
        return "🔐 Ошибка авторизации. Обратитесь к администратору."
    
    elif "network" in error_str or "connection" in error_str:
        return "🌐 Проблемы с сетью. Проверьте соединение и попробуйте снова."
    
    elif "file" in error_str and "size" in error_str:
        return "📁 Файл слишком большой. Уменьшите размер и попробуйте снова."
    
    else:
        return "❌ Произошла ошибка. Попробуйте позже или обратитесь к администратору."


def log_user_action(user_id: int, action: str, success: bool = True, details: Dict[str, Any] = None):
    """Логирует действия пользователей"""
    status = "✅" if success else "❌"
    details_str = f" | {details}" if details else ""
    logger.info(f"{status} User {user_id} | Action: {action}{details_str}")


def log_api_call(api_name: str, duration: float, success: bool = True, error: str = None):
    """Логирует вызовы API"""
    status = "✅" if success else "❌"
    error_str = f" | Error: {error}" if error else ""
    logger.info(f"{status} API {api_name} | Duration: {duration:.2f}s{error_str}")
