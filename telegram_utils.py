import asyncio
import logging
import re
from telegram.constants import ChatAction, ParseMode
from telegram import Update
from telegram.ext import CallbackContext


logger = logging.getLogger(__name__)


ADVERTISEMENT_REGEX = re.compile(
    r'^\s*---\s*\n\*\*Sponsor\*\*[\s\S]*?https?://pollinations\.ai/redirect-nexad/\w+[\s\S]*?$',
    re.IGNORECASE | re.MULTILINE
)


async def show_typing(context: CallbackContext, chat_id: int):
    while True:
        try:
            await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)
        except Exception as e:
            logger.debug(f"show_typing error: {e}")
        await asyncio.sleep(5)


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
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки части {i+1}/{len(parts)}: {str(e)}")


async def delete_advertisement(update: Update, context: CallbackContext):
    message = update.effective_message
    text = message.text or message.caption or ""

    if ADVERTISEMENT_REGEX.search(text):
        try:
            await message.delete()

            warning = await message.reply_text(
                "🚫 Рекламные сообщения запрещены!",
                reply_to_message_id=message.message_id
            )

            await asyncio.sleep(5)
            await warning.delete()

            logger.info(f"Удалено рекламное сообщение в чате {message.chat_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления рекламы: {str(e)}")
            await message.reply_text(
                "⚠️ Не удалось удалить рекламное сообщение. Проверьте права бота!",
                reply_to_message_id=message.message_id
            )
    return False


