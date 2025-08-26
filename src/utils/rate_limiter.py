import time
import asyncio
import logging
from typing import Dict, List, Optional
from collections import defaultdict
from config.settings import settings


logger = logging.getLogger(__name__)


class RateLimiter:
    """Улучшенный rate limiter с sliding window"""
    
    def __init__(self):
        self.user_requests: Dict[int, List[float]] = defaultdict(list)
        self.chat_requests: Dict[int, List[float]] = defaultdict(list)
        # Комбинированные запросы пользователь+чат для более гибкого rate limiting
        self.user_chat_requests: Dict[tuple, List[float]] = defaultdict(list)
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def _cleanup_old_requests(self, requests: List[float], window_seconds: int):
        """Удаляет старые запросы из окна"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Удаляем запросы старше окна
        while requests and requests[0] < cutoff_time:
            requests.pop(0)
    
    def check_rate_limit(self, user_id: int, chat_id: int = None, 
                        min_interval: float = None, 
                        max_per_minute: int = None) -> bool:
        """
        Проверяет rate limit для пользователя и чата
        
        Args:
            user_id: ID пользователя
            chat_id: ID чата (опционально)
            min_interval: Минимальный интервал между запросами в секундах
            max_per_minute: Максимальное количество запросов в минуту
            
        Returns:
            True если запрос разрешен, False если превышен лимит
        """
        current_time = time.time()
        
        # Используем настройки по умолчанию если не указаны
        min_interval = min_interval or settings.min_request_interval
        max_per_minute = max_per_minute or settings.max_requests_per_minute
        
        # Проверяем лимит по комбинации пользователь+чат (основной подход)
        if chat_id:
            user_chat_key = (user_id, chat_id)
            user_chat_requests = self.user_chat_requests[user_chat_key]
            self._cleanup_old_requests(user_chat_requests, 60)
            
            # Проверяем минимальный интервал для конкретного чата
            if user_chat_requests and (current_time - user_chat_requests[-1]) < min_interval:
                return False
            
            # Проверяем лимит запросов в минуту для конкретного чата
            if len(user_chat_requests) >= max_per_minute:
                return False
        
        # Проверяем лимит по чату (если указан)
        if chat_id:
            chat_requests = self.chat_requests[chat_id]
            self._cleanup_old_requests(chat_requests, 60)
            
            # Для чатов более строгий лимит
            chat_max_per_minute = max_per_minute // 2
            if len(chat_requests) >= chat_max_per_minute:
                return False
        
        # УБРАЛИ глобальные лимиты пользователя - они блокировали запросы в разных чатах
        # Теперь каждый чат имеет независимые лимиты
        
        return True
    
    def record_request(self, user_id: int, chat_id: int = None):
        """Записывает новый запрос"""
        current_time = time.time()
        
        # УБРАЛИ запись в глобальный user_requests - он больше не используется для проверки
        # self.user_requests[user_id].append(current_time)
        
        # Записываем запрос чата (если указан)
        if chat_id:
            self.chat_requests[chat_id].append(current_time)
            # Записываем комбинированный запрос пользователь+чат
            user_chat_key = (user_id, chat_id)
            self.user_chat_requests[user_chat_key].append(current_time)
    
    def get_wait_time(self, user_id: int, chat_id: int = None) -> float:
        """Возвращает время ожидания до следующего разрешенного запроса"""
        current_time = time.time()
        min_interval = settings.min_request_interval
        
        wait_time = 0
        
        # Проверяем время до следующего разрешенного запроса для конкретного чата
        if chat_id:
            user_chat_key = (user_id, chat_id)
            user_chat_requests = self.user_chat_requests[user_chat_key]
            if user_chat_requests:
                last_request = user_chat_requests[-1]
                wait_time = max(0, min_interval - (current_time - last_request))
        
        # Проверяем глобальный лимит пользователя (более мягкий)
        user_requests = self.user_requests[user_id]
        if user_requests:
            last_request = user_requests[-1]
            global_min_interval = min_interval * 0.1  # В 10 раз мягче
            global_wait_time = max(0, global_min_interval - (current_time - last_request))
            wait_time = max(wait_time, global_wait_time)
        
        # Проверяем время до освобождения слота в чате
        if chat_id:
            chat_requests = self.chat_requests[chat_id]
            self._cleanup_old_requests(chat_requests, 60)
            
            if len(chat_requests) >= settings.max_requests_per_minute // 2:
                # Нужно подождать до освобождения слота
                oldest_request = chat_requests[0]
                chat_wait_time = 60 - (current_time - oldest_request)
                wait_time = max(wait_time, chat_wait_time)
        
        return wait_time
    
    async def cleanup_old_data(self):
        """Периодически очищает старые данные"""
        while True:
            try:
                current_time = time.time()
                
                # Очищаем данные пользователей старше 1 часа
                for user_id in list(self.user_requests.keys()):
                    self._cleanup_old_requests(self.user_requests[user_id], 3600)
                    if not self.user_requests[user_id]:
                        del self.user_requests[user_id]
                
                # Очищаем данные чатов старше 1 часа
                for chat_id in list(self.chat_requests.keys()):
                    self._cleanup_old_requests(self.chat_requests[chat_id], 3600)
                    if not self.chat_requests[chat_id]:
                        del self.chat_requests[chat_id]
                
                # Очищаем комбинированные данные пользователь+чат старше 1 часа
                for user_chat_key in list(self.user_chat_requests.keys()):
                    self._cleanup_old_requests(self.user_chat_requests[user_chat_key], 3600)
                    if not self.user_chat_requests[user_chat_key]:
                        del self.user_chat_requests[user_chat_key]
                
                # Ждем 5 минут до следующей очистки
                await asyncio.sleep(300)
                
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка в cleanup_old_data: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке
    
    def start_cleanup_task(self):
        """Запускает задачу очистки"""
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self.cleanup_old_data())
    
    def stop_cleanup_task(self):
        """Останавливает задачу очистки"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()


# Глобальный экземпляр rate limiter
rate_limiter = RateLimiter()
