import logging
from telegram.ext import ContextTypes

from services.context_manager import context_manager

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=True)
    if update and hasattr(update, 'message'):
        try:
            msg = await update.message.reply_text("⚠️ Произошла внутренняя ошибка. Пожалуйста, попробуйте снова.")
            try:
                chat_id = update.effective_chat.id
                context_manager.add_cleanup_message(chat_id, msg.message_id)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e}")
