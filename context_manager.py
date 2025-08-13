import logging
import time


logger = logging.getLogger(__name__)

class ContextManager:
    def __init__(self):
        self.contexts = {}
        self.generating_flags = {}
        self.user_last_request = {}  # Для rate limiting
        # Системный промпт по умолчанию
        self.system_prompt = (
            "Ты - полезный ассистент по имени СикСик. "
            "Отвечай кратко, по делу и дружелюбно. "
            "Если тебя спрашивают о чем-то, что ты не знаешь, честно скажи об этом. "
            "Используй эмодзи для лучшего восприятия."
        )

    def init_context(self, chat_id):
        if chat_id not in self.contexts:
            self.contexts[chat_id] = []
            self.generating_flags[chat_id] = False

    def reset_context(self, chat_id):
        if chat_id in self.contexts:
            self.contexts[chat_id] = []
        self.generating_flags[chat_id] = False

    def add_message(self, chat_id, role, content, author=None):
        self.init_context(chat_id)
        entry = {"role": role, "content": content}
        if author is not None:
            entry["author"] = author
        self.contexts[chat_id].append(entry)

        # Ограничиваем размер контекста (последние 20 сообщений)
        if len(self.contexts[chat_id]) > 20:
            self.contexts[chat_id] = self.contexts[chat_id][-20:]

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
        if self.system_prompt:
            api_messages.append({"role": "system", "content": self.system_prompt})
        
        for msg in self.contexts[chat_id]:
            role = msg.get("role")
            content = msg.get("content", "")
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
    
    def set_system_prompt(self, prompt: str):
        """Устанавливает системный промпт"""
        self.system_prompt = prompt
        logger.info("Системный промпт обновлен")
    
    def get_system_prompt(self) -> str:
        """Возвращает текущий системный промпт"""
        return self.system_prompt
    
    def reset_system_prompt(self):
        """Сбрасывает системный промпт к значению по умолчанию"""
        self.system_prompt = (
            "Ты - полезный ассистент по имени СикСик. "
            "Отвечай кратко, по делу и дружелюбно. "
            "Если тебя спрашивают о чем-то, что ты не знаешь, честно скажи об этом. "
            "Используй эмодзи для лучшего восприятия."
        )
        logger.info("Системный промпт сброшен к значению по умолчанию")


# Глобальный экземпляр менеджера контекста
context_manager = ContextManager()


