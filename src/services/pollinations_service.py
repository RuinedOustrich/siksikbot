import logging
import requests
import base64
import json
import urllib.parse
from typing import Optional, Tuple


logger = logging.getLogger(__name__)


def encode_media_base64(file_path: str) -> str:
    """Кодирует файл в base64"""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка кодирования файла: {e}")
        return None


def transcribe_audio(audio_path: str, token: str) -> str:
    """Транскрибирует аудио через Pollinations.AI"""
    base64_audio = encode_media_base64(audio_path)
    if not base64_audio:
        return None

    audio_format = audio_path.split('.')[-1].lower()
    supported_formats = ['mp3', 'wav', 'ogg', 'm4a', 'flac']
    if audio_format not in supported_formats:
        logger.warning(f"Неподдерживаемый формат аудио: {audio_format}")
        return None

    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "model": "openai-audio",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this audio"},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64_audio,
                            "format": audio_format
                        }
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        content = result.get('choices', [{}])[0].get('message', {}).get('content')
        if not content or not content.strip():
            return None
        return content
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return None


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


def send_to_pollinations(messages: list, token: str, model: str = "openai") -> str:
    """Отправляет POST-запрос к Pollinations.AI API и возвращает ответ"""
    url = "https://text.pollinations.ai/openai"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "model": model,
        "messages": messages,
        "seed": 42,
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        response.raise_for_status()
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
    except requests.exceptions.RequestException as e:
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


