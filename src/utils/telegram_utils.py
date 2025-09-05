import asyncio
import logging
import re
from telegram.constants import ChatAction, ParseMode
from telegram import Update
from telegram.ext import CallbackContext
from config.settings import settings


logger = logging.getLogger(__name__)


# Паттерны для различных типов рекламы
ADVERTISEMENT_PATTERNS = [
    # Оригинальный паттерн для pollinations.ai
    re.compile(
        r'-{3,}\s*\n\*\*Sponsor\*\*[\s\S]*?https?://pollinations\.ai/redirect-nexad/\w+[\s\S]*?',
        re.IGNORECASE
    ),
    # Универсальный паттерн - удаляет всё от ?userid= до конца текста
    re.compile(
        r'\?userid=\d+\)[\s\S]*$',
        re.IGNORECASE
    ),
]


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
    """Экранирует специальные символы Markdown для Telegram"""
    # Специальные символы, которые нужно экранировать в Telegram Markdown
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    escaped_text = text
    for char in special_chars:
        escaped_text = escaped_text.replace(char, f'\\{char}')
    
    return escaped_text


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


def safe_format_for_telegram(text: str) -> str:
    """Безопасное форматирование текста для Telegram с дополнительными проверками"""
    try:
        # Сначала применяем обычное форматирование
        formatted = format_for_telegram_markdown(text)
        
        # Дополнительные проверки на корректность Markdown
        # Проверяем баланс звездочек для жирного текста
        asterisk_count = formatted.count('*')
        if asterisk_count % 2 != 0:
            # Если нечетное количество звездочек, добавляем одну в конец
            formatted += '*'
        
        # Проверяем баланс подчеркиваний для курсива
        underscore_count = formatted.count('_')
        if underscore_count % 2 != 0:
            # Если нечетное количество подчеркиваний, добавляем одно в конец
            formatted += '_'
        
        # Проверяем корректность ссылок [text](url)
        # Если есть открывающая скобка без закрывающей
        if formatted.count('[') > formatted.count(']'):
            # Добавляем закрывающую скобку
            formatted += ']'
        
        # Если есть открывающая круглая скобка без закрывающей в ссылках
        link_pattern = r'\[([^\]]*)\]\(([^)]*)$'
        if re.search(link_pattern, formatted):
            formatted += ')'
        
        return formatted
    except Exception as e:
        logger.debug(f"safe_format_for_telegram error: {e}")
        # В случае ошибки возвращаем исходный текст без форматирования
        return text


async def send_long_message(context: CallbackContext, chat_id: int, text: str, reply_to_message_id: int = None):
    """Отправляет длинное сообщение с поддержкой Markdown и fallback на обычный текст"""
    # Подготавливаем текст под Telegram Markdown (в т.ч. заголовки ### -> *...*)
    text = safe_format_for_telegram(text)

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
        # Сначала пробуем отправить с Markdown
        try:
            if i == 0 and reply_to_message_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.debug(f"Markdown send failed for part {i+1}/{len(parts)}: {e}")
            # Если Markdown не работает, отправляем без форматирования
            try:
                if i == 0 and reply_to_message_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        reply_to_message_id=reply_to_message_id
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=part
                    )
            except Exception as e2:
                logger.error(f"Ошибка отправки части {i+1}/{len(parts)}: {str(e2)}")
        await asyncio.sleep(0.5)





def strip_advertisement(text: str) -> str:
    """Удаляет рекламные блоки из текста, оставляя остальной текст без изменений."""
    try:
        cleaned_text = text
        original_length = len(text)
        
        for i, pattern in enumerate(ADVERTISEMENT_PATTERNS):
            before_length = len(cleaned_text)
            cleaned_text = re.sub(pattern, "", cleaned_text)
            after_length = len(cleaned_text)
            
            if before_length != after_length:
                logger.info(f"Реклама удалена паттерном {i+1}: {before_length - after_length} символов")
        
        # Дополнительная очистка: удаляем лишние пробелы и переносы строк
        cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)  # Убираем множественные пустые строки
        cleaned_text = re.sub(r'[ \t]+', ' ', cleaned_text)  # Убираем множественные пробелы и табуляции, но сохраняем переносы строк
        cleaned_text = cleaned_text.strip()
        
        # Если после очистки текст стал слишком коротким, возможно, мы удалили слишком много
        if len(cleaned_text) < len(text) * 0.3:  # Если осталось меньше 30% от исходного текста
            logger.warning(f"Возможно, удалено слишком много текста: {len(text)} -> {len(cleaned_text)} символов")
        
        final_length = len(cleaned_text)
        if original_length != final_length:
            logger.info(f"Общая очистка рекламы: {original_length} -> {final_length} символов")
        
        return cleaned_text
    except Exception as e:
        logger.debug(f"strip_advertisement error: {e}")
        return text
