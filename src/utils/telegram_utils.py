import asyncio
import logging
import re
from telegram.constants import ChatAction, ParseMode
from telegram import Update
from telegram.ext import CallbackContext
from config.settings import settings


logger = logging.getLogger(__name__)


ADVERTISEMENT_REGEX = re.compile(
    r'-{3,}\s*\n\*\*Sponsor\*\*[\s\S]*?https?://pollinations\.ai/redirect-nexad/\w+[\s\S]*?',
    re.IGNORECASE
)


async def show_typing(context: CallbackContext, chat_id: int):
    try:
        interval = getattr(settings, "typing_interval", 5)
        while True:
            try:
                await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)
            except Exception as e:
                logger.debug(f"show_typing error: {e}")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.debug("show_typing task cancelled")
        return


def _escape_markdown(text: str) -> str:
    # Экранируем спецсимволы Markdown V2 при необходимости
    # Сейчас используем ParseMode.MARKDOWN (не V2), но оставим функцию на будущее
    return text


def format_for_telegram_markdown(text: str) -> str:
    """Преобразует распространённые, но неподдерживаемые конструкции Markdown в формат Telegram Markdown.

    Что делаем:
    - Заголовки вида #, ##, ###, ... конвертируем в жирную строку: "*Заголовок*"
    - Внутри блоков кода ```...``` ничего не меняем
    """
    try:
        lines = text.splitlines()
        out_lines = []
        inside_code_block = False
        for line in lines:
            stripped = line.lstrip()

            # Переключение режима для блоков кода
            if stripped.startswith("```"):
                inside_code_block = not inside_code_block
                out_lines.append(line)
                continue

            if not inside_code_block:
                # Заголовки: #### Title #### -> *Title*
                m = re.match(r'^\s*(#{1,6})\s+(.+?)\s*$', line)
                if m:
                    content = m.group(2)
                    # Удаляем возможные завершающие #
                    content = re.sub(r'\s*#+\s*$', '', content)
                    line = f"*{content}*"

            out_lines.append(line)
        return "\n".join(out_lines)
    except Exception as e:
        logger.debug(f"format_for_telegram_markdown error: {e}")
        return text


async def send_long_message(context: CallbackContext, chat_id: int, text: str, reply_to_message_id: int = None):
    # Подготавливаем текст под Telegram Markdown (в т.ч. заголовки ### -> *...*)
    text = format_for_telegram_markdown(text)

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
        safe_part = _escape_markdown(part)
        try:
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
        except Exception as e:
            logger.debug(f"Markdown send failed for part {i+1}/{len(parts)}: {e}")
            try:
                if i == 0 and reply_to_message_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=safe_part,
                        reply_to_message_id=reply_to_message_id
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=safe_part
                    )
            except Exception as e2:
                logger.error(f"Ошибка отправки части {i+1}/{len(parts)}: {str(e2)}")
        await asyncio.sleep(0.5)





def strip_advertisement(text: str) -> str:
    """Удаляет рекламные блоки из текста, оставляя остальной текст без изменений."""
    try:
        # Удаляем один или несколько рекламных блоков где бы они ни находились
        return re.sub(ADVERTISEMENT_REGEX, "", text).strip()
    except Exception as e:
        logger.debug(f"strip_advertisement error: {e}")
        return text
