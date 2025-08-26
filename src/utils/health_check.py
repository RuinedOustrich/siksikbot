"""
Модуль для проверки состояния бота и сбора метрик
"""
import time
import psutil
import logging
from typing import Dict, Any
from services.context_manager import context_manager

logger = logging.getLogger(__name__)

# Глобальные метрики
_start_time = time.time()
_request_count = 0
_error_count = 0


def increment_request_count():
    """Увеличивает счетчик запросов"""
    global _request_count
    _request_count += 1


def increment_error_count():
    """Увеличивает счетчик ошибок"""
    global _error_count
    _error_count += 1


def get_health_status() -> Dict[str, Any]:
    """Возвращает статус здоровья бота"""
    try:
        # Получаем информацию о системе
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage('/')
        
        # Получаем информацию о контекстах
        active_contexts = len(context_manager.contexts)
        total_messages = sum(len(msgs) for msgs in context_manager.contexts.values())
        
        # Вычисляем uptime
        uptime_seconds = time.time() - _start_time
        uptime_hours = uptime_seconds / 3600
        
        # Вычисляем статистику ошибок
        error_rate = (_error_count / _request_count * 100) if _request_count > 0 else 0
        
        return {
            "status": "healthy",
            "uptime_hours": round(uptime_hours, 2),
            "uptime_seconds": int(uptime_seconds),
            "memory_usage_percent": memory_info.percent,
            "memory_available_mb": round(memory_info.available / 1024 / 1024, 2),
            "disk_usage_percent": disk_info.percent,
            "disk_free_gb": round(disk_info.free / 1024 / 1024 / 1024, 2),
            "active_contexts": active_contexts,
            "total_messages": total_messages,
            "request_count": _request_count,
            "error_count": _error_count,
            "error_rate_percent": round(error_rate, 2),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Ошибка получения статуса здоровья: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


def get_performance_metrics() -> Dict[str, Any]:
    """Возвращает метрики производительности"""
    try:
        # Получаем статистику по чатам
        chat_stats = {}
        for chat_id, messages in context_manager.contexts.items():
            user_messages = len([msg for msg in messages if msg.get("role") == "user"])
            assistant_messages = len([msg for msg in messages if msg.get("role") == "assistant"])
            
            chat_stats[str(chat_id)] = {
                "total_messages": len(messages),
                "user_messages": user_messages,
                "assistant_messages": assistant_messages,
                "context_size": len(messages)
            }
        
        return {
            "total_chats": len(context_manager.contexts),
            "chat_statistics": chat_stats,
            "average_context_size": sum(len(msgs) for msgs in context_manager.contexts.values()) / max(len(context_manager.contexts), 1),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Ошибка получения метрик производительности: {e}")
        return {
            "error": str(e),
            "timestamp": time.time()
        }
