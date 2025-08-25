import asyncio
import logging
import re
from telegram.constants import ChatAction, ParseMode
from telegram import Update
from telegram.ext import CallbackContext


logger = logging.getLogger(__name__)


ADVERTISEMENT_REGEX = re.compile(
    r'-{3,}\s*\n\*\*Sponsor\*\*[\s\S]*?https?://pollinations\.ai/redirect-nexad/\w+[\s\S]*?',
    re.IGNORECASE
)


async def show_typing(context: CallbackContext, chat_id: int):
    while True:
        try:
            await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)
        except Exception as e:
            logger.debug(f"show_typing error: {e}")
        await asyncio.sleep(5)


def _escape_markdown(text: str) -> str:
    # Экранируем спецсимволы Markdown V2 при необходимости
    # Сейчас используем ParseMode.MARKDOWN (не V2), но оставим функцию на будущее
    return text


async def send_long_message(context: CallbackContext, chat_id: int, text: str, reply_to_message_id: int = None):
    parts = []
    while text:
        if len(text) > 4000:
            split_index = text[:4000].rfind('\n')
            if split_index == -1:
                split_index = text[:4000].rfind(' ')
            if split_index == -1:
                split_index = 4000
            parts.append(text[:split_index])
            text = text[split_index:].lstrip()
        else:
            parts.append(text)
            text = ""

    for i, part in enumerate(parts):
        try:
            safe_part = _escape_markdown(part)
            if i == 0 and reply_to_message_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=safe_part,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=safe_part,
                    parse_mode=ParseMode.MARKDOWN
                )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки части {i+1}/{len(parts)}: {str(e)}")


async def delete_advertisement(update: Update, context: CallbackContext):
    message = update.effective_message
    text = message.text or message.caption or ""
    
    logger.info(f"Проверка на рекламу в сообщении {message.message_id}: {text[:50]}...")

    if ADVERTISEMENT_REGEX.search(text):
        # Пытаемся удалить только рекламный блок из текста
        stripped = strip_advertisement(text)
        if stripped != text:
            try:
                if message.text:
                    await message.edit_text(stripped, parse_mode=ParseMode.MARKDOWN)
                elif message.caption:
                    await message.edit_caption(stripped, parse_mode=ParseMode.MARKDOWN)
                logger.info(f"Обрезан рекламный блок в сообщении {message.message_id} чата {message.chat.id}")
                # Не прерываем другие хендлеры
                return True
            except Exception as e:
                logger.debug(f"Не удалось отредактировать сообщение для удаления рекламы: {e}")
        # Если не удалось отредактировать (например, чужое сообщение) — просто продолжим
    return False


def strip_advertisement(text: str) -> str:
    """Удаляет рекламные блоки из текста, оставляя остальной текст без изменений."""
    try:
        # Удаляем один или несколько рекламных блоков где бы они ни находились
        return re.sub(ADVERTISEMENT_REGEX, "", text).strip()
    except Exception as e:
        logger.debug(f"strip_advertisement error: {e}")
        return text


