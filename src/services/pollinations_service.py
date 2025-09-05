import logging
import os
import requests
import aiohttp
import asyncio
import base64
import json
import urllib.parse
from typing import Optional, Tuple


logger = logging.getLogger(__name__)

# Глобальная сессия aiohttp для переиспользования
_http_session = None
_connector = None

async def get_http_session():
    """Получает или создает глобальную HTTP сессию с пулом соединений"""
    global _http_session, _connector
    if _http_session is None or _http_session.closed:
        # Создаем коннектор с пулом соединений для параллельных запросов
        _connector = aiohttp.TCPConnector(
            limit=500,  # УВЕЛИЧИЛИ: Общий лимит соединений
            limit_per_host=100,  # УВЕЛИЧИЛИ: Лимит соединений на хост (было 30)
            ttl_dns_cache=300,  # Кэш DNS на 5 минут
            use_dns_cache=True,
            force_close=False,  # НЕ закрывать соединения принудительно
            enable_cleanup_closed=True,  # Очищать закрытые соединения
        )
        timeout = aiohttp.ClientTimeout(total=60)
        _http_session = aiohttp.ClientSession(
            connector=_connector,
            timeout=timeout
        )
    return _http_session

async def close_http_session():
    """Закрывает глобальную HTTP сессию и коннектор"""
    global _http_session, _connector
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None
    if _connector and not _connector.closed:
        await _connector.close()
        _connector = None


def encode_media_base64(file_path: str) -> str:
    """Кодирует файл в base64 с проверкой размера"""
    try:
        # Проверяем размер файла перед чтением
        file_size = os.path.getsize(file_path)
        max_size = 50 * 1024 * 1024  # 50MB
        
        if file_size > max_size:
            logger.error(f"Файл слишком большой: {file_size} байт")
            return None
            
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка кодирования файла: {e}")
        return None


def transcribe_audio(audio_path: str, token: str) -> str:
    """Транскрибирует аудио через Pollinations.AI с улучшенной обработкой отказов"""
    base64_audio = encode_media_base64(audio_path)
    if not base64_audio:
        return None

    audio_format = audio_path.split('.')[-1].lower()
    supported_formats = ['mp3', 'wav', 'ogg', 'm4a', 'flac']
    if audio_format not in supported_formats:
        logger.warning(f"Неподдерживаемый формат аудио: {audio_format}")
        return None

    # Попытка транскрипции
    result = _attempt_transcription(base64_audio, audio_format, token)
    if result and not _is_refusal_response(result):
        return result
    
    # Если транскрипция не удалась или дала отказ, возвращаем fallback
    logger.warning("Транскрипция не удалась или дала отказ")
    return _get_transcription_fallback_message()


async def transcribe_audio_async(audio_path: str, token: str) -> str:
    """Асинхронно транскрибирует аудио через Pollinations.AI с улучшенной обработкой отказов"""
    base64_audio = encode_media_base64(audio_path)
    if not base64_audio:
        return None

    audio_format = audio_path.split('.')[-1].lower()
    supported_formats = ['mp3', 'wav', 'ogg', 'm4a', 'flac']
    if audio_format not in supported_formats:
        logger.warning(f"Неподдерживаемый формат аудио: {audio_format}")
        return None

    # Попытка асинхронной транскрипции
    result = await _attempt_transcription_async(base64_audio, audio_format, token)
    if result and not _is_refusal_response(result):
        return result
    
    # Если транскрипция не удалась или дала отказ, возвращаем fallback
    logger.warning("Транскрипция не удалась или дала отказ")
    return _get_transcription_fallback_message()


def _attempt_transcription(base64_audio: str, audio_format: str, token: str) -> str:
    """Попытка транскрипции аудио"""
    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # Оптимальный промпт для транскрипции
    system_prompt = (
        "Ты - профессиональный транскриптор. Твоя задача - точно перевести речь в текст. "
        "Ты всегда выполняешь транскрипцию, независимо от качества аудио. "
        "Сохраняй пунктуацию и структуру предложений. Не добавляй комментарии - только транскрипцию. "
        "Не интерпретируй и не дополняй содержание - только дословная транскрипция того, что сказано."
    )

    payload = {
        "model": "openai-audio",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64_audio,
                            "format": audio_format
                        }
                    }
                ]
            }
        ],
        "temperature": 0.3,  # Оптимальная температура для транскрипции
        "max_tokens": 1000
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        content = result.get('choices', [{}])[0].get('message', {}).get('content')
        
        if not content or not content.strip():
            return None
        
        # Очищаем транскрипцию от возможных артефактов
        content = content.strip()
        
        # Удаляем возможные префиксы, которые модель может добавить
        unwanted_prefixes = [
            "Транскрипция:",
            "Текст:",
            "Содержание:",
            "Аудио содержит:",
            "В аудио говорится:",
            "Transcription:",
            "Text:",
            "Content:",
            "Audio contains:",
            "The audio says:",
            "Извините, я не могу",
            "Я не могу",
            "Sorry, I cannot",
            "I cannot"
        ]
        
        for prefix in unwanted_prefixes:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()
                break
        
        # Удаляем возможные суффиксы
        unwanted_suffixes = [
            "Это транскрипция аудио.",
            "Это текст из аудио.",
            "This is audio transcription.",
            "This is text from audio."
        ]
        
        for suffix in unwanted_suffixes:
            if content.endswith(suffix):
                content = content[:-len(suffix)].strip()
                break
        
        # Проверяем, не является ли результат отказом
        if _is_refusal_response(content):
            logger.warning(f"Транскрипция дала отказ: {content[:50]}...")
            return None
        
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return None


async def _attempt_transcription_async(base64_audio: str, audio_format: str, token: str) -> str:
    """Асинхронная попытка транскрипции аудио"""
    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # Оптимальный промпт для транскрипции
    system_prompt = (
        "Ты - профессиональный транскриптор. Твоя задача - точно перевести речь в текст. "
        "Ты всегда выполняешь транскрипцию, независимо от качества аудио. "
        "Сохраняй пунктуацию и структуру предложений. Не добавляй комментарии - только транскрипцию. "
        "Не интерпретируй и не дополняй содержание - только дословная транскрипция того, что сказано."
    )

    payload = {
        "model": "openai-audio",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64_audio,
                            "format": audio_format
                        }
                    }
                ]
            }
        ],
        "temperature": 0.3,  # Оптимальная температура для транскрипции
        "max_tokens": 1000
    }

    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload) as response:
            response.raise_for_status()
            result = await response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content')
            
            if not content or not content.strip():
                return None
            
            # Очищаем транскрипцию от возможных артефактов
            content = content.strip()
            
            # Удаляем возможные префиксы, которые модель может добавить
            unwanted_prefixes = [
                "Транскрипция:",
                "Текст:",
                "Содержание:",
                "Аудио содержит:",
                "В аудио говорится:",
                "Transcription:",
                "Text:",
                "Content:",
                "Audio contains:",
                "The audio says:",
                "Извините, я не могу",
                "Я не могу",
                "Sorry, I cannot",
                "I cannot"
            ]
            
            for prefix in unwanted_prefixes:
                if content.startswith(prefix):
                    content = content[len(prefix):].strip()
                    break
            
            # Удаляем возможные суффиксы
            unwanted_suffixes = [
                "Это транскрипция аудио.",
                "Это текст из аудио.",
                "This is audio transcription.",
                "This is text from audio."
            ]
            
            for suffix in unwanted_suffixes:
                if content.endswith(suffix):
                    content = content[:-len(suffix)].strip()
                    break
            
            # Проверяем, не является ли результат отказом
            if _is_refusal_response(content):
                logger.warning(f"Транскрипция дала отказ: {content[:50]}...")
                return None
            
            return content if content else None
            
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return None


def _get_transcription_fallback_message() -> str:
    """Возвращает fallback сообщение для случаев, когда транскрипция не удалась"""
    import random
    
    fallback_messages = [
        "🤔 Извините, но я не могу помочь с этим запросом. Попробуйте сформулировать вопрос по-другому.",
        "😅 К сожалению, я не могу обработать это сообщение. Можете попробовать переформулировать ваш вопрос?",
        "🤷‍♂️ Я не могу помочь с этим запросом. Попробуйте задать вопрос в другом формате.",
        "😊 Извините, но я не могу ответить на это сообщение. Попробуйте переформулировать ваш вопрос.",
        "🤔 К сожалению, я не могу помочь с этим. Можете попробовать задать вопрос по-другому?",
        "😅 Я не могу обработать этот запрос. Попробуйте сформулировать вопрос иначе.",
        "🤷‍♀️ Извините, но я не могу помочь с этим сообщением. Попробуйте переформулировать вопрос.",
        "😊 К сожалению, я не могу ответить на этот запрос. Можете попробовать задать вопрос по-другому?"
    ]
    
    return random.choice(fallback_messages)


def _is_fallback_message(text: str) -> bool:
    """Проверяет, является ли текст fallback сообщением для транскрипции"""
    if not text:
        return False
    
    # Ключевые фразы, которые указывают на fallback сообщения
    fallback_indicators = [
        "не могу помочь с этим",
        "не могу обработать это",
        "не могу ответить на это",
        "не могу помочь с этим запросом",
        "не могу обработать этот запрос",
        "не могу ответить на этот запрос",
        "не могу помочь с этим сообщением",
        "попробуйте сформулировать",
        "попробуйте переформулировать",
        "попробуйте задать вопрос",
        "сформулировать вопрос по-другому",
        "переформулировать ваш вопрос",
        "задать вопрос в другом формате",
        "сформулировать вопрос иначе"
    ]
    
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in fallback_indicators)


def analyze_image(image_path: str, token: str, question: str = "Что на этом изображении?", system_prompt: Optional[str] = None) -> str:
    """Анализирует изображение через Pollinations.AI.
    Если ответ пуст с system-role, пробуем fallback: передаём инструкции в тексте пользователя.
    """
    base64_image = encode_media_base64(image_path)
    if not base64_image:
        return None

    image_format = image_path.split('.')[-1].lower()
    supported_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    if image_format not in supported_formats:
        logger.warning(f"Неподдерживаемый формат изображения: {image_format}")
        return None

    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    def _post_messages(messages):
        payload = {
            "model": "openai",
            "messages": messages,
            "max_tokens": 2000
        }
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()

    # Первая попытка: system-role (если задан)
    messages_primary = []
    if system_prompt:
        messages_primary.append({
            "role": "system",
            "content": system_prompt
        })
    messages_primary.append({
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{image_format};base64,{base64_image}"
                }
            }
        ]
    })

    try:
        result = _post_messages(messages_primary)
        content = result.get('choices', [{}])[0].get('message', {}).get('content')
        if content and content.strip():
            return content
    except Exception as e:
        logger.warning(f"analyse_image primary attempt failed: {e}")

    # Fallback: инструкции переносим в user-текст, без system-role
    try:
        user_text = question
        if system_prompt:
            user_text = f"Инструкции: {system_prompt}\n\n{question}"
        messages_fallback = [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{image_format};base64,{base64_image}"
                    }
                }
            ]
        }]
        result_fb = _post_messages(messages_fallback)
        content_fb = result_fb.get('choices', [{}])[0].get('message', {}).get('content')
        if content_fb and content_fb.strip():
            logger.info("analyse_image: used fallback without system-role")
            return content_fb
    except Exception as e:
        logger.error(f"analyse_image fallback failed: {e}")

    return None


async def analyze_image_async(image_path: str, token: str, question: str = "Что на этом изображении?", system_prompt: Optional[str] = None) -> str:
    """Асинхронно анализирует изображение через Pollinations.AI.
    Если ответ пуст с system-role, пробуем fallback: передаём инструкции в тексте пользователя.
    """
    base64_image = encode_media_base64(image_path)
    if not base64_image:
        return None

    image_format = image_path.split('.')[-1].lower()
    supported_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    if image_format not in supported_formats:
        logger.warning(f"Неподдерживаемый формат изображения: {image_format}")
        return None

    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    async def _post_messages_async(messages):
        payload = {
            "model": "openai",
            "messages": messages,
            "max_tokens": 2000
        }
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload) as response:
            response.raise_for_status()
            return await response.json()

    # Первая попытка: system-role (если задан)
    messages_primary = []
    if system_prompt:
        messages_primary.append({
            "role": "system",
            "content": system_prompt
        })
    messages_primary.append({
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{image_format};base64,{base64_image}"
                }
            }
        ]
    })

    try:
        result = await _post_messages_async(messages_primary)
        content = result.get('choices', [{}])[0].get('message', {}).get('content')
        if content and content.strip():
            return content
    except Exception as e:
        logger.warning(f"analyse_image primary attempt failed: {e}")

    # Fallback: инструкции переносим в user-текст, без system-role
    try:
        user_text = question
        if system_prompt:
            user_text = f"Инструкции: {system_prompt}\n\n{question}"
        messages_fallback = [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{image_format};base64,{base64_image}"
                    }
                }
            ]
        }]
        result_fb = await _post_messages_async(messages_fallback)
        content_fb = result_fb.get('choices', [{}])[0].get('message', {}).get('content')
        if content_fb and content_fb.strip():
            logger.info("analyse_image: used fallback without system-role")
            return content_fb
    except Exception as e:
        logger.error(f"analyse_image fallback failed: {e}")

    return None


def _is_refusal_response(response_text: str) -> bool:
    """Проверяет, является ли ответ отказом в помощи"""
    if not response_text:
        return False
    
    # Если строка состоит только из пробелов - это не отказ
    if not response_text.strip():
        return False
    
    response_lower = response_text.lower().strip()
    
    # Список явных отказов
    explicit_refusals = [
        "извините", "sorry", "i'm sorry", "i am sorry",
        "не могу", "can't", "cannot", "can not",
        "не в состоянии", "unable", "not able",
        "не способен", "not capable",
        "отказываюсь", "refuse", "decline",
        "не буду", "will not", "won't",
        "не подходит", "not appropriate", "inappropriate",
        "не предназначен", "not designed", "not meant",
        "обратитесь к", "consult", "contact",
        "выходит за рамки", "beyond", "outside",
        "не подходящая тема", "not suitable topic",
        "уважительное общение", "respectful communication",
        "поддерживать общение", "support communication"
    ]
    
    # Проверяем явные отказы
    for refusal in explicit_refusals:
        if refusal in response_lower:
            return True
    
    # Проверяем длину - слишком короткие ответы часто являются отказами
    stripped = response_text.strip()
    if len(stripped) < 10 and len(stripped) > 0:
        return True
    
    # Проверяем, содержит ли ответ только служебные слова
    service_words = [
        "транскрипция", "transcription", "аудио", "audio", 
        "сообщение", "message", "запрос", "request",
        "помощь", "help", "поддержка", "support"
    ]
    
    words = response_lower.split()
    if len(words) <= 3:
        # Если очень мало слов, проверяем, не состоит ли ответ только из служебных
        if all(word in service_words for word in words):
            return True
    
    # Проверяем на формальные фразы
    formal_phrases = [
        "я здесь", "i'm here", "i am here",
        "пожалуйста", "please",
        "обратите внимание", "please note", "please be",
        "содержание", "content",
        "сообщений", "messages"
    ]
    
    for phrase in formal_phrases:
        if phrase in response_lower:
            return True
    
    return False


def _validate_messages_and_token(messages: list, token: str) -> tuple[bool, str]:
    """Валидирует сообщения и токен, возвращает (is_valid, error_message)"""
    if not token or token.strip() == "":
        logger.error("Токен Pollinations не предоставлен")
        return False, "❌ Ошибка конфигурации: токен не предоставлен"
    
    if not messages or len(messages) == 0:
        logger.error("Список сообщений пуст")
        return False, "❌ Ошибка: нет сообщений для отправки"
    
    # Проверяем формат сообщений
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
            logger.error(f"Неверный формат сообщения {i}: {msg}")
            return False, "❌ Ошибка: неверный формат сообщений"
    
    # Проверяем общую длину сообщений
    total_length = sum(len(str(msg.get('content', ''))) for msg in messages)
    if total_length > 100000:  # Лимит в 100KB
        logger.warning(f"Общая длина сообщений слишком большая: {total_length} символов")
        # Обрезаем сообщения, оставляя только последние
        while total_length > 50000 and len(messages) > 1:
            messages.pop(0)  # Удаляем самое старое сообщение
            total_length = sum(len(str(msg.get('content', ''))) for msg in messages)
        logger.info(f"Обрезали сообщения до {len(messages)} сообщений, общая длина: {total_length}")
    
    return True, ""


def send_to_pollinations(messages: list, token: str, model: str = "openai") -> str:
    """Отправляет POST-запрос к Pollinations.AI API и возвращает ответ"""
    # Валидация входных данных
    is_valid, error_message = _validate_messages_and_token(messages, token)
    if not is_valid:
        return error_message
    
    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "model": model,
        "messages": messages,
        "seed": 42,
        "max_tokens": 2000
    }

    try:
        # Логируем детали запроса для диагностики
        logger.info(f"Отправляем запрос к Pollinations API: {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload keys: {list(payload.keys())}")
        logger.info(f"Messages count: {len(payload.get('messages', []))}")
        
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        # Проверяем статус ответа
        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Pollinations API вернул статус {response.status_code}: {error_text}")
            logger.error(f"Request headers: {headers}")
            logger.error(f"Request payload: {payload}")
            return f"❌ Ошибка API (статус {response.status_code}): {error_text}"

        result = response.json()

        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            if not content or not content.strip():
                logger.warning("Получен пустой ответ от API")
                return "❌ Получен пустой ответ от API"
            return content
        elif "response" in result:
            content = result["response"]
            if not content or not content.strip():
                logger.warning("Получен пустой ответ от API")
                return "❌ Получен пустой ответ от API"
            return content
        else:
            logger.error(f"Неожиданный формат ответа: {result}")
            return "❌ Получен неожиданный формат ответа от API"

    except requests.exceptions.Timeout:
        logger.error("Таймаут запроса к Pollinations API")
        return "❌ Таймаут запроса к API. Попробуйте снова."
    except requests.exceptions.HTTPError as e:
        error_text = e.response.text if e.response else ""
        logger.error(f"HTTP ошибка {e.response.status_code if e.response else 'unknown'} от Pollinations API: {error_text}")
        logger.error(f"Request headers: {headers}")
        logger.error(f"Request payload: {payload}")
        return f"❌ Ошибка API (статус {e.response.status_code if e.response else 'unknown'}): {error_text}"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к Pollinations: {str(e)}")
        return f"❌ Ошибка сети: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON ответа: {e}")
        return "❌ Ошибка обработки ответа от сервера"
    except Exception as e:
        logger.exception("Неожиданная ошибка")
        return f"❌ Ошибка: {str(e)}"


async def send_to_pollinations_async(messages: list, token: str, model: str = "openai") -> str:
    """Асинхронно отправляет POST-запрос к Pollinations.AI API и возвращает ответ"""
    # Валидация входных даннpых
    is_valid, error_message = _validate_messages_and_token(messages, token)
    if not is_valid:
        return error_message
    
    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "model": model,
        "messages": messages,
        "seed": 42,
        "max_tokens": 2000
    }

    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload) as response:
            # Логируем детали запроса для диагностики
            logger.info(f"Отправляем запрос к Pollinations API: {url}")
            logger.info(f"Headers: {headers}")
            logger.info(f"Payload keys: {list(payload.keys())}")
            logger.info(f"Messages count: {len(payload.get('messages', []))}")
            
            # Проверяем статус ответа
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Pollinations API вернул статус {response.status}: {error_text}")
                logger.error(f"Request headers: {headers}")
                logger.error(f"Request payload: {payload}")
                return f"❌ Ошибка API (статус {response.status}): {error_text}"
            
            result = await response.json()

            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    logger.warning("Получен пустой ответ от API")
                    return "❌ Получен пустой ответ от API"
                return content
            elif "response" in result:
                content = result["response"]
                if not content or not content.strip():
                    logger.warning("Получен пустой ответ от API")
                    return "❌ Получен пустой ответ от API"
                return content
            else:
                logger.error(f"Неожиданный формат ответа: {result}")
                return "❌ Получен неожиданный формат ответа от API"

    except asyncio.TimeoutError:
        logger.error("Таймаут запроса к Pollinations API")
        return "❌ Таймаут запроса к API. Попробуйте снова."
    except aiohttp.ClientResponseError as e:
        error_text = ""
        try:
            error_text = await e.response.text()
        except:
            pass
        logger.error(f"HTTP ошибка {e.status} от Pollinations API: {error_text}")
        logger.error(f"Request headers: {headers}")
        logger.error(f"Request payload: {payload}")
        return f"❌ Ошибка API (статус {e.status}): {error_text}"
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка запроса к Pollinations: {str(e)}")
        return f"❌ Ошибка сети: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON ответа: {e}")
        return "❌ Ошибка обработки ответа от сервера"
    except Exception as e:
        logger.exception("Неожиданная ошибка")
        return f"❌ Ошибка: {str(e)}"


# -------- Генерация изображений по описанию --------
def generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: Optional[int] = None, model: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
    """Генерирует изображение через Pollinations Image API и возвращает (bytes, url).

    Возвращает bytes изображения (или None при ошибке) и итоговый URL.
    """
    try:
        # Базовый эндпоинт. Параметры width/height/seed поддерживаются Pollinations
        encoded_prompt = urllib.parse.quote(prompt)
        params = {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = str(seed)
        if model:
            params["model"] = model

        query = urllib.parse.urlencode(params)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?{query}"
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content, url
    except Exception as e:
        logger.error(f"Ошибка генерации изображения: {e}")
        return None, None


async def generate_image_async(prompt: str, width: int = 1024, height: int = 1024, seed: Optional[int] = None, model: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
    """Асинхронно генерирует изображение через Pollinations Image API и возвращает (bytes, url).

    Возвращает bytes изображения (или None при ошибке) и итоговый URL.
    """
    try:
        # Базовый эндпоинт. Параметры width/height/seed поддерживаются Pollinations
        encoded_prompt = urllib.parse.quote(prompt)
        params = {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = str(seed)
        if model:
            params["model"] = model

        query = urllib.parse.urlencode(params)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?{query}"
        
        # Используем глобальную сессию aiohttp для переиспользования
        session = await get_http_session()
        async with session.get(url) as response:
            response.raise_for_status()
            content = await response.read()
            return content, url
    except asyncio.CancelledError:
        logger.warning("Генерация изображения была отменена пользователем")
        raise  # Передаем отмену выше
    except asyncio.TimeoutError:
        logger.error("Таймаут при генерации изображения")
        return None, None
    except Exception as e:
        logger.error(f"Ошибка генерации изображения: {e}")
        return None, None


async def auto_analyze_generated_image(image_content: bytes, prompt: str, token: str) -> Optional[str]:
    """Автоматически анализирует сгенерированное изображение и возвращает описание.
    
    Эта функция используется для сохранения контекста о сгенерированных изображениях.
    """
    if not image_content or not token:
        return None
        
    try:
        # Создаем временный файл для анализа
        import tempfile
        import uuid
        
        temp_dir = tempfile.mkdtemp()
        image_path = os.path.join(temp_dir, f"generated_{uuid.uuid4()}.jpg")
        
        try:
            # Сохраняем изображение во временный файл
            with open(image_path, 'wb') as f:
                f.write(image_content)
            
            # Анализируем изображение с специальным промптом для контекста
            analysis_question = f"Опиши это изображение, созданное по запросу '{prompt}'. Что получилось?"
            system_prompt = (
                "Ты анализируешь изображение, созданное ИИ по запросу пользователя. "
                "Дай описание того, что получилось в 3-4 предложениях: основные объекты, их расположение, стиль, настроение. "
                "Твой анализ будет сохранен в контекст диалога для дальнейшего использования. "
                "Будь информативен, но не слишком многословен."
            )
            
            analysis_result = await analyze_image_async(
                image_path=image_path,
                token=token,
                question=analysis_question,
                system_prompt=system_prompt
            )
            
            return analysis_result
            
        finally:
            # Очищаем временные файлы
            try:
                import shutil
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Не удалось удалить временные файлы анализа: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка автоматического анализа изображения: {e}")
        return None


