"""
Декораторы для улучшения обработки ошибок и логирования
"""
import asyncio
import logging
import time
import functools
from typing import Callable, Any
from telegram import Update
from telegram.ext import CallbackContext

logger = logging.getLogger(__name__)


def handle_errors(func: Callable) -> Callable:
    """Декоратор для обработки ошибок в обработчиках команд"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Ошибка в {func.__name__}: {e}")
            
            # Отправляем пользователю понятное сообщение об ошибке
            if update and update.effective_message:
                try:
                    error_message = _get_user_friendly_error(e)
                    error_msg = await update.effective_message.reply_text(error_message)
                    
                    # Добавляем сообщение об ошибке в список для автоматического удаления
                    from services.context_manager import context_manager
                    chat_id = update.effective_chat.id if update.effective_chat else None
                    if chat_id and error_msg:
                        context_manager.add_cleanup_message(chat_id, error_msg.message_id)
                        
                except Exception as send_error:
                    logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")
            
            # Не поднимаем исключение дальше, чтобы не прерывать работу бота
            return None
    
    return wrapper


def track_performance(func: Callable) -> Callable:
    """Декоратор для отслеживания производительности"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(f"{func.__name__} выполнен за {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{func.__name__} завершился с ошибкой после {duration:.2f}s: {e}")
            raise
    
    return wrapper


def _get_user_friendly_error(error: Exception) -> str:
    """Возвращает понятное пользователю сообщение об ошибке"""
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
    
    elif "validation" in error_str or "invalid" in error_str:
        return "❌ Некорректные данные. Проверьте введенную информацию."
    
    else:
        return "❌ Произошла ошибка. Попробуйте позже или обратитесь к администратору."
