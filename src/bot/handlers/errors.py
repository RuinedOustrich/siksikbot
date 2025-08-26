import logging
from telegram.ext import ContextTypes

from services.context_manager import context_manager

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=True)
    try:
        effective_message = getattr(update, 'effective_message', None)
        if effective_message is not None:
            msg = await effective_message.reply_text("⚠️ Произошла внутренняя ошибка. Пожалуйста, попробуйте снова.")
            try:
                chat_id = getattr(update, 'effective_chat', None).id if getattr(update, 'effective_chat', None) else None
                if chat_id:
                    context_manager.add_cleanup_message(chat_id, msg.message_id)
                    # При глобальной ошибке НЕ очищаем список - сообщение об ошибке само добавлено в список
                    # для удаления при следующем успешном ответе
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")
