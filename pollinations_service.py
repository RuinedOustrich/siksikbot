import logging
import requests
import base64
import json


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


def analyze_image(image_path: str, token: str, question: str = "Что на этом изображении?") -> str:
    """Анализирует изображение через Pollinations.AI"""
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

    payload = {
        "model": "openai",
        "messages": [
            {
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
            }
        ],
        "max_tokens": 2000
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result.get('choices', [{}])[0].get('message', {}).get('content')
    except Exception as e:
        logger.error(f"Ошибка анализа изображения: {e}")
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


