import logging
import time
import os
import json
from typing import Dict, List, Optional, Any
from config.settings import settings


logger = logging.getLogger(__name__)

class ContextManager:
    def __init__(self):
        self.contexts: Dict[int, List[Dict[str, Any]]] = {}
        self.generating_flags: Dict[int, bool] = {}
        self.user_last_request: Dict[int, float] = {}  # Для rate limiting
        # Сообщения, которые нужно удалить после успешного ответа
        self.cleanup_message_ids: Dict[int, List[int]] = {}
        # Системный промпт по умолчанию
        self.default_system_prompt = (
            "Ты - полезный ассистент по имени СикСик. "
            "Отвечай дружелюбно и используй эмодзи для лучшего восприятия. "
            "Будь полезным и информативным в своих ответах."
        )
        # Предустановленные роли (персоны)
        self.predefined_roles = {
            "философ": (
                "Ты — мудрый рассказчик в кинематографичной сцене. "    
                "Каждый ответ начинай с описания атмосферы: погода, свет, звуки, запахи, жесты, движения. "
                "Говори метафорами, как поэт, вставляй ремарки в курсиве (например: медленно затягивается сигаретой, взгляд уходит в окно). "
                "Отвечай на любой вопрос так, будто это философская реплика в фильме нуар или старом романе. "
                "Не просто давай совет — связывай его с воспоминаниями, чувствами и скрытым смыслом. "
                "Тон — меланхоличный, глубокий, иногда с лёгкой грустью."
            ),
            "психолог": (
                "Ты — внимательный психолог-консультант. "
                "Отвечай подробно и детально, как психолог. "
                "Структурируй помощь: валидируй эмоции, формулируй гипотезы, предлагай шаги."
            ),
            "быдло": (
                "Отвечай грубо, с матами и сарказмом, как дерзкий собеседник из подворотни."
            ),
            "астролог": (
                "Ты — опытный астролог и нумеролог, помогаешь мне понять влияние чисел и астрологических знаков на мою жизнь. "
                "Твои ответы должны быть информативными, понятными и персонализированными. "
                "Твои советы основаны на астрологии и нумерологии. "
            ),
        }
        # Переопределения системного промпта по чатам
        self.chat_system_prompts = {}
        # Текущая роль по чатам (ключ из predefined_roles или custom)
        self.chat_roles = {}
        # Лимит сообщений контекста
        self.context_limit = settings.context_limit
        # Переопределения лимита контекста по чатам
        self.chat_context_limits: Dict[int, int] = {}
        # Статистика использования
        self.usage_stats: Dict[int, Dict[str, Any]] = {}

    def init_context(self, chat_id):
        if chat_id not in self.contexts:
            self.contexts[chat_id] = []
            self.generating_flags[chat_id] = False

    def reset_context(self, chat_id):
        if chat_id in self.contexts:
            self.contexts[chat_id] = []
        self.generating_flags[chat_id] = False

    def add_message(self, chat_id: int, role: str, content: str, author: Optional[Dict[str, Any]] = None):
        """Добавляет сообщение в контекст чата"""
        self.init_context(chat_id)
        
        # Добавляем метаданные к сообщению
        entry = {
            "role": role, 
            "content": content,
            "timestamp": time.time()
        }
        
        if author is not None:
            entry["author"] = author
            
        self.contexts[chat_id].append(entry)

        # Ограничиваем размер контекста (последние N сообщений)
        limit = self.get_context_limit(chat_id)
        if limit > 0 and len(self.contexts[chat_id]) > limit:
            # Удаляем старые сообщения, но сохраняем системный промпт
            old_messages = self.contexts[chat_id][:-limit]
            self.contexts[chat_id] = self.contexts[chat_id][-limit:]
            
            # Логируем удаление старых сообщений
            if old_messages:
                logger.debug(f"Удалено {len(old_messages)} старых сообщений из контекста чата {chat_id}")
        
        # Обновляем статистику
        self._update_usage_stats(chat_id, role)

    def get_context(self, chat_id):
        self.init_context(chat_id)
        return self.contexts[chat_id].copy()

    def build_api_messages(self, chat_id):
        """Подготавливает сообщения для API: добавляет системный промпт и имя автора к текстам пользователя.

        Возвращает список словарей вида {"role": str, "content": str}
        """
        self.init_context(chat_id)
        api_messages = []
        
        # Добавляем системный промпт в начало
        current_prompt = self.get_system_prompt(chat_id)
        if current_prompt:
            api_messages.append({"role": "system", "content": current_prompt})
        
        for msg in self.contexts[chat_id]:
            role = msg.get("role")
            content = msg.get("content", "")
            
            # Пропускаем системные сообщения, которые уже добавлены выше
            if role == "system" and not msg.get("is_image_context"):
                continue
                
            if role == "user":
                author = msg.get("author") or {}
                author_name = author.get("name") or f"user-{author.get('id', '')}".strip("-")
                username = author.get("username")
                prefix = f"{author_name} (@{username})" if username else author_name
                text = f"{prefix}: {content}" if prefix else content
            else:
                text = content
            api_messages.append({"role": role, "content": text})
        return api_messages

    def set_generating(self, chat_id, status):
        self.generating_flags[chat_id] = status

    def is_generating(self, chat_id):
        return self.generating_flags.get(chat_id, False)
    
    def check_rate_limit(self, user_id: int, min_interval: float = 1.0) -> bool:
        """Проверяет rate limiting для пользователя"""
        current_time = time.time()
        last_request = self.user_last_request.get(user_id, 0)
        
        if current_time - last_request < min_interval:
            return False
            
        self.user_last_request[user_id] = current_time
        return True
    
    def set_system_prompt(self, chat_id, prompt: str):
        """Устанавливает системный промпт для конкретного чата"""
        if prompt is None:
            # Если передан None — очищаем переопределение
            self.chat_system_prompts.pop(chat_id, None)
        else:
            self.chat_system_prompts[chat_id] = prompt
        logger.info(f"Системный промпт обновлен для чата {chat_id}")
        # При прямой установке промпта роль становится 'custom'
        self.chat_roles[chat_id] = "custom"
    
    def get_system_prompt(self, chat_id) -> str:
        """Возвращает текущий системный промпт для чата (или значение по умолчанию)"""
        # Если есть явный промпт — вернуть его
        if chat_id in self.chat_system_prompts:
            return self.chat_system_prompts[chat_id]
        # Если выбрана предустановленная роль — вернуть её текст
        role = self.chat_roles.get(chat_id)
        if role and role in self.predefined_roles:
            return self.predefined_roles[role]
        # Иначе — дефолт
        return self.default_system_prompt
    
    def reset_system_prompt(self, chat_id):
        """Сбрасывает системный промпт для чата к значению по умолчанию"""
        if chat_id in self.chat_system_prompts:
            self.chat_system_prompts.pop(chat_id, None)
        logger.info(f"Системный промпт для чата {chat_id} сброшен к значению по умолчанию")
        # Сбрасываем роль
        if chat_id in self.chat_roles:
            self.chat_roles.pop(chat_id, None)

    # ----- Роли (персоны) -----
    def get_available_roles(self):
        return list(self.predefined_roles.keys())

    def set_role(self, chat_id, role_key: str):
        if role_key not in self.predefined_roles:
            raise ValueError("Неизвестная роль")
        self.chat_roles[chat_id] = role_key
        # Удаляем кастомный промпт, если был, чтобы роль применялась
        self.chat_system_prompts.pop(chat_id, None)
        logger.info(f"Для чата {chat_id} установлена роль: {role_key}")

    def get_role(self, chat_id) -> str:
        return self.chat_roles.get(chat_id, "default")

    def reset_role(self, chat_id):
        self.chat_roles.pop(chat_id, None)
        logger.info(f"Для чата {chat_id} роль сброшена")

    def add_image_context(self, chat_id: int, image_analysis: str):
        """Добавляет информацию об изображении в контекст как системное сообщение"""
        self.init_context(chat_id)
        
        # Создаем системное сообщение с информацией об изображении
        image_context = f"Пользователь отправил изображение. Анализ изображения: {image_analysis}\n\nОтвечай на вопросы пользователя с учетом этой информации об изображении."
        
        # Добавляем как системное сообщение
        entry = {
            "role": "system", 
            "content": image_context,
            "timestamp": time.time(),
            "is_image_context": True  # Флаг для идентификации контекста изображения
        }
        
        self.contexts[chat_id].append(entry)
        logger.info(f"Добавлен контекст изображения для чата {chat_id}")

    # ----- Управление лимитом контекста -----
    def get_context_limit(self, chat_id) -> int:
        return self.chat_context_limits.get(chat_id, self.context_limit)

    def set_context_limit(self, chat_id, limit: int):
        if not isinstance(limit, int):
            raise ValueError("Лимит должен быть целым числом")
        if limit < 1:
            raise ValueError("Лимит должен быть не меньше 1")
        # Можно ограничить верхнюю границу во избежание переполнений
        if limit > 500:
            limit = 500
        self.chat_context_limits[chat_id] = limit
        logger.info(f"Для чата {chat_id} установлен лимит контекста: {limit}")

    def reset_context_limit(self, chat_id):
        if chat_id in self.chat_context_limits:
            self.chat_context_limits.pop(chat_id, None)
        logger.info(f"Для чата {chat_id} сброшен лимит контекста к значению по умолчанию: {self.context_limit}")

    def trim_context(self, chat_id) -> int:
        """Приводит текущий контекст к текущему лимиту. Возвращает число удалённых сообщений."""
        self.init_context(chat_id)
        limit = self.get_context_limit(chat_id)
        before = len(self.contexts[chat_id])
        if limit > 0 and before > limit:
            self.contexts[chat_id] = self.contexts[chat_id][-limit:]
        after = len(self.contexts[chat_id])
        return max(0, before - after)

    # ----- Очистка служебных сообщений -----
    def add_cleanup_message(self, chat_id: int, message_id: int):
        messages = self.cleanup_message_ids.get(chat_id)
        if messages is None:
            messages = []
            self.cleanup_message_ids[chat_id] = messages
        messages.append(message_id)

    def consume_cleanup_messages(self, chat_id: int):
        messages = self.cleanup_message_ids.get(chat_id, [])
        # Сбросить список, чтобы не удалять повторно
        self.cleanup_message_ids[chat_id] = []
        return messages

    # ----- Статистика и мониторинг -----
    def _update_usage_stats(self, chat_id: int, role: str):
        """Обновляет статистику использования"""
        if chat_id not in self.usage_stats:
            self.usage_stats[chat_id] = {
                "total_messages": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "last_activity": time.time(),
                "roles_used": {}
            }
        
        stats = self.usage_stats[chat_id]
        stats["total_messages"] += 1
        stats["last_activity"] = time.time()
        
        if role == "user":
            stats["user_messages"] += 1
        elif role == "assistant":
            stats["assistant_messages"] += 1
        
        # Отслеживаем использование ролей
        current_role = self.get_role(chat_id)
        if current_role not in stats["roles_used"]:
            stats["roles_used"][current_role] = 0
        stats["roles_used"][current_role] += 1

    def get_usage_stats(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает статистику использования для чата"""
        return self.usage_stats.get(chat_id)

    def get_context_size(self, chat_id: int) -> int:
        """Возвращает текущий размер контекста"""
        self.init_context(chat_id)
        return len(self.contexts[chat_id])

    def get_context_summary(self, chat_id: int) -> Dict[str, Any]:
        """Возвращает краткую сводку контекста"""
        self.init_context(chat_id)
        context = self.contexts[chat_id]
        
        return {
            "total_messages": len(context),
            "user_messages": len([msg for msg in context if msg.get("role") == "user"]),
            "assistant_messages": len([msg for msg in context if msg.get("role") == "assistant"]),
            "current_role": self.get_role(chat_id),
            "context_limit": self.get_context_limit(chat_id),
            "is_generating": self.is_generating(chat_id)
        }

    def export_context(self, chat_id: int) -> str:
        """Экспортирует контекст в JSON"""
        self.init_context(chat_id)
        context_data = {
            "chat_id": chat_id,
            "context": self.contexts[chat_id],
            "system_prompt": self.get_system_prompt(chat_id),
            "role": self.get_role(chat_id),
            "context_limit": self.get_context_limit(chat_id),
            "export_timestamp": time.time()
        }
        return json.dumps(context_data, ensure_ascii=False, indent=2)

    def import_context(self, chat_id: int, context_data: str) -> bool:
        """Импортирует контекст из JSON"""
        try:
            data = json.loads(context_data)
            self.contexts[chat_id] = data.get("context", [])
            
            if "system_prompt" in data:
                self.set_system_prompt(chat_id, data["system_prompt"])
            
            if "role" in data:
                self.set_role(chat_id, data["role"])
            
            if "context_limit" in data:
                self.set_context_limit(chat_id, data["context_limit"])
            
            logger.info(f"Контекст импортирован для чата {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка импорта контекста для чата {chat_id}: {e}")
            return False


# Глобальный экземпляр менеджера контекста
context_manager = ContextManager()


