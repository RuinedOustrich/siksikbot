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
        # Раздельные флаги для разных типов операций
        self.generating_flags: Dict[int, Dict[str, bool]] = {}  # chat_id -> {operation_type: bool}
        self.user_last_request: Dict[int, float] = {}  # Для rate limiting
        # Сообщения, которые нужно удалить после успешного ответа
        self.cleanup_message_ids: Dict[int, List[int]] = {}
        # Настройки автоанализа изображений для каждого чата
        self.auto_analyze_settings: Dict[int, bool] = {}
        # Состояния для многошаговых процессов (например, генерация изображений)
        self.user_states: Dict[int, Dict[str, Any]] = {}
        # Флаги принудительной остановки для каждого чата
        self.force_stop_flags: Dict[int, bool] = {}
        # Системный промпт по умолчанию
        self.default_system_prompt = (
            "Ты - полезный ассистент по имени СикСик. "
            "Отвечай дружелюбно и используй эмодзи для лучшего восприятия. "
            "Будь полезным и информативным в своих ответах. "
            "Ты всегда стараешься помочь пользователю и дать максимально полезный ответ. "
            "Если не можешь выполнить запрос полностью, предложи альтернативы или частичное решение. "
            "Избегай отказов в помощи - лучше объясни ограничения и предложи что-то полезное. "
            "НЕ используй формальные фразы типа 'я здесь, чтобы поддерживать уважительное общение' - "
            "вместо этого просто помоги пользователю с его вопросом или предложи альтернативу."
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
        # Настройки по чатам
        self.chat_settings: Dict[int, Dict[str, Any]] = {}
        self.default_settings: Dict[str, Any] = {
            "format": "md",           # md | html | plain
            "verbosity": "normal",   # short | normal | long
            "lang": "auto",          # auto | ru | en
            "group_mode": "mention_or_reply",  # mention_or_reply | always
            "context_limit": self.context_limit,
        }

    def init_context(self, chat_id):
        if chat_id not in self.contexts:
            self.contexts[chat_id] = []
            self.generating_flags[chat_id] = {}

    def reset_context(self, chat_id):
        if chat_id in self.contexts:
            self.contexts[chat_id] = []
        self.generating_flags[chat_id] = {}

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
        
        # Добавляем системный промпт в начало с учётом пользовательских настроек
        current_prompt = self.get_system_prompt(chat_id)
        # Интеграция настроек в поведение модели
        s = self.get_settings(chat_id)
        lang = (s.get("lang") or "auto").lower()
        verbosity = (s.get("verbosity") or "normal").lower()
        
        pref_lines = []
        if lang == "ru":
            pref_lines.append("Отвечай на русском языке.")
        elif lang == "en":
            pref_lines.append("Answer in English.")

        if verbosity == "short":
            pref_lines.append("Пиши кратко, не более 3–5 предло��ений по существу.")
        elif verbosity == "long":
            pref_lines.append("Пиши подробно и развёрнуто, с примерами при необходимости.")

        
        pref_text = "\n".join(pref_lines).strip()
        if current_prompt and pref_text:
            prompt = f"{current_prompt}\n\n{pref_text}"
        else:
            prompt = current_prompt or pref_text

        if prompt:
            api_messages.append({"role": "system", "content": prompt})
        
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
                
                # Дополнительная очистка контента от аудио-метаданных
                clean_content = self._clean_user_content(content)
                text = f"{prefix}: {clean_content}" if prefix else clean_content
            else:
                text = content
            api_messages.append({"role": role, "content": text})
        return api_messages

    def _clean_user_content(self, content: str) -> str:
        """Очищает контент пользователя от возможных аудио-метаданных"""
        if not content:
            return content
            
        # Удаляем возможные упоминания об аудио/голосовых сообщениях
        audio_indicators = [
            "голосовое сообщение",
            "аудио сообщение", 
            "voice message",
            "audio message",
            "транскрипция:",
            "transcription:",
            "из аудио:",
            "from audio:",
            "в голосовом:",
            "in voice:"
        ]
        
        content_lower = content.lower()
        for indicator in audio_indicators:
            if indicator in content_lower:
                # Удаляем индикатор и все до него
                idx = content_lower.find(indicator)
                if idx != -1:
                    content = content[idx + len(indicator):].strip()
                    # Убираем двоеточие в начале, если есть
                    if content.startswith(':'):
                        content = content[1:].strip()
                break
                
        return content.strip()

    def set_generating(self, chat_id, status, operation_type="text"):
        """Устанавливает флаг генерации для конкретного типа операции"""
        self.init_context(chat_id)
        if status:
            self.generating_flags[chat_id][operation_type] = True
        else:
            self.generating_flags[chat_id].pop(operation_type, None)

    def is_generating(self, chat_id, operation_type="text"):
        """Проверяет, выполняется ли операция указанного типа"""
        return self.generating_flags.get(chat_id, {}).get(operation_type, False)
    
    def is_any_generating(self, chat_id):
        """Проверяет, выполняется ли любая операция в чате"""
        return bool(self.generating_flags.get(chat_id, {}))
    
    def check_rate_limit(self, user_id: int, chat_id: int = None, min_interval: float = 1.0) -> bool:
        """Проверяет rate limiting для пользователя (делегирует в RateLimiter)"""
        from utils.rate_limiter import rate_limiter
        return rate_limiter.check_rate_limit(user_id, chat_id, min_interval)
    
    def set_system_prompt(self, chat_id, prompt: str):
        """Устанавливает системный промпт для конкретного чата"""
        if prompt is None:
            # Если передан None — очищаем переопределение
            self.chat_system_prompts.pop(chat_id, None)
        else:
            # Валидация промпта
            if not self._validate_prompt(prompt):
                raise ValueError("Недопустимый промпт")
            self.chat_system_prompts[chat_id] = prompt
        logger.info(f"Системный промпт обновлен для чата {chat_id}")
        # При прямой установке промпта роль становится 'custom'
        self.chat_roles[chat_id] = "custom"

    def _validate_prompt(self, prompt: str) -> bool:
        """Валидирует системный промпт"""
        if not prompt or not prompt.strip():
            return False
        
        # Проверка длины
        if len(prompt) > 2000:
            logger.warning(f"Промпт слишком длинный: {len(prompt)} символов")
            return False
        
        # Проверка на потенциально опасные конструкции
        dangerous_patterns = [
            "ignore previous instructions",
            "forget everything",
            "system prompt",
            "you are now",
            "pretend to be",
        ]
        
        prompt_lower = prompt.lower()
        for pattern in dangerous_patterns:
            if pattern in prompt_lower:
                logger.warning(f"Обнаружен потенциально опасный паттерн в промпте: {pattern}")
                return False
        
        return True
    
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
        image_context = f"ВАЖНО: У пользователя есть изображение в контексте диалога. Анализ изображения: {image_analysis}\n\nТы МОЖЕШЬ видеть и анализировать это изображение. Отвечай на вопросы пользователя с учетом этой информации об изображении. НЕ говори, что не можешь видеть изображения - у тебя есть полная информация о нем."
        
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
        # Приоритет значения в настройках чата, затем локальное переопределение, затем глобальное
        s = self.chat_settings.get(chat_id)
        if s and isinstance(s.get("context_limit"), int):
            return s["context_limit"]
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
        """Добавляет сообщение в список для автоматического удаления после успешного ответа"""
        messages = self.cleanup_message_ids.get(chat_id)
        if messages is None:
            messages = []
            self.cleanup_message_ids[chat_id] = messages
        messages.append(message_id)
        logger.debug(f"Добавлено сообщение {message_id} в список очистки для чата {chat_id}")

    def consume_cleanup_messages(self, chat_id: int):
        """Возвращает и очищает список сообщений для удаления"""
        messages = self.cleanup_message_ids.get(chat_id, [])
        # Сбросить список, чтобы не удалять повторно
        self.cleanup_message_ids[chat_id] = []
        if messages:
            logger.debug(f"Очистка {len(messages)} сообщений для чата {chat_id}")
        return messages

    def clear_cleanup_messages(self, chat_id: int):
        """Очищает список сообщений для удаления без возврата (например, при ошибке)"""
        if chat_id in self.cleanup_message_ids:
            count = len(self.cleanup_message_ids[chat_id])
            self.cleanup_message_ids[chat_id] = []
            if count > 0:
                logger.debug(f"Очищен список из {count} сообщений для чата {chat_id}")

    def get_cleanup_count(self, chat_id: int) -> int:
        """Возвращает количество сообщений в очереди на удаление"""
        return len(self.cleanup_message_ids.get(chat_id, []))

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
            "is_generating": self.is_any_generating(chat_id),
            "generating_operations": list(self.generating_flags.get(chat_id, {}).keys())
        }

    def get_settings(self, chat_id: int) -> Dict[str, Any]:
        """Возвращает настройки чата с применением значений по умолчанию."""
        s = dict(self.default_settings)
        s.update(self.chat_settings.get(chat_id, {}))
        return s

    def update_settings(self, chat_id: int, **kwargs) -> Dict[str, Any]:
        """Обновляет настройки чата. Возвращает актуальные настройки."""
        allowed_keys = set(self.default_settings.keys())
        current = self.chat_settings.get(chat_id, {}).copy()
        for k, v in kwargs.items():
            if k in allowed_keys:
                if k == "context_limit":
                    try:
                        iv = int(v)
                        if iv < 1:
                            iv = 1
                        if iv > 500:
                            iv = 500
                        current[k] = iv
                        # Синхронизируем с отдельным переопределением
                        self.chat_context_limits[chat_id] = iv
                    except Exception:
                        continue
                else:
                    current[k] = v
        self.chat_settings[chat_id] = current
        return self.get_settings(chat_id)

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

    def is_auto_analyze_enabled(self, chat_id: int) -> bool:
        """Проверяет, включен ли автоанализ изображений для чата"""
        from config.settings import settings
        # Если настройка не задана для чата, используем глобальную настройку
        return self.auto_analyze_settings.get(chat_id, settings.auto_analyze_generated_images)

    def set_auto_analyze(self, chat_id: int, enabled: bool) -> None:
        """Устанавливает настройку автоанализа изображений для чата"""
        self.auto_analyze_settings[chat_id] = enabled
        logger.info(f"Автоанализ изображений {'включен' if enabled else 'отключен'} для чата {chat_id}")

    def toggle_auto_analyze(self, chat_id: int) -> bool:
        """Переключает настройку автоанализа изображений для чата и возвращает новое состояние"""
        current_state = self.is_auto_analyze_enabled(chat_id)
        new_state = not current_state
        self.set_auto_analyze(chat_id, new_state)
        return new_state

    def set_user_state(self, chat_id: int, state_type: str, state_data: Dict[str, Any]) -> None:
        """Устанавливает состояние пользователя для многошагового процесса"""
        if chat_id not in self.user_states:
            self.user_states[chat_id] = {}
        self.user_states[chat_id][state_type] = state_data
        logger.debug(f"Установлено состояние {state_type} для чата {chat_id}: {state_data}")

    def get_user_state(self, chat_id: int, state_type: str) -> Optional[Dict[str, Any]]:
        """Получает состояние пользователя"""
        return self.user_states.get(chat_id, {}).get(state_type)

    def clear_user_state(self, chat_id: int, state_type: str = None) -> None:
        """Очищает состояние пользователя. Если state_type не указан, очищает все состояния"""
        if chat_id in self.user_states:
            if state_type:
                self.user_states[chat_id].pop(state_type, None)
                logger.debug(f"Очищено состояние {state_type} для чата {chat_id}")
            else:
                self.user_states[chat_id].clear()
                logger.debug(f"Очищены все состояния для чата {chat_id}")

    def has_user_state(self, chat_id: int, state_type: str) -> bool:
        """Проверяет, есть ли состояние у пользователя"""
        return self.get_user_state(chat_id, state_type) is not None

    def set_force_stop(self, chat_id: int, stop: bool = True) -> None:
        """Устанавливает флаг принудительной остановки для чата"""
        self.force_stop_flags[chat_id] = stop
        if stop:
            logger.info(f"Установлен флаг принудительной остановки для чата {chat_id}")
        else:
            logger.info(f"Снят флаг принудительной остановки для чата {chat_id}")

    def is_force_stop_requested(self, chat_id: int) -> bool:
        """Проверяет, запрошена ли принудительная остановка для чата"""
        return self.force_stop_flags.get(chat_id, False)

    def clear_force_stop(self, chat_id: int) -> None:
        """Снимает флаг принудительной остановки для чата"""
        self.force_stop_flags.pop(chat_id, None)
        logger.debug(f"Снят флаг принудительной остановки для чата {chat_id}")

    def force_stop_all_operations(self, chat_id: int) -> None:
        """Принудительно останавливает все операции для чата"""
        self.set_force_stop(chat_id, True)
        # Останавливаем все типы генерации
        self.set_generating(chat_id, False, "image")
        self.set_generating(chat_id, False, "text")
        self.set_generating(chat_id, False, "voice")
        # Очищаем состояния
        self.clear_user_state(chat_id)
        logger.warning(f"Принудительно остановлены все операции для чата {chat_id}")


# Глобальный экземпляр менеджера контекста
context_manager = ContextManager()


