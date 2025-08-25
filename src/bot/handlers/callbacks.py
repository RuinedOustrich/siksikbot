import logging
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.context_manager import context_manager
from services.pollinations_service import generate_image

logger = logging.getLogger(__name__)


async def _safe_edit_query_message(query, text, reply_markup=None):
    try:
        m = query.message
        if m and (m.caption is not None or m.photo or m.document or m.video):
            return await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        return await query.edit_message_text(text=text, reply_markup=reply_markup)
    except Exception:
        return None


async def role_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("role::"):
        return
    _, value = data.split("::", 1)
    chat_id = query.message.chat.id
    if value == "reset":
        context_manager.reset_role(chat_id)
        await query.edit_message_text("✅ Роль сброшена. Используется промпт по умолчанию.")
        return
    try:
        context_manager.set_role(chat_id, value)
        current_prompt = context_manager.get_system_prompt(chat_id)
        await query.edit_message_text(
            f"✅ Роль установлена: {value}\n\nНовый системный стиль:\n{current_prompt}"
        )
    except ValueError:
        await query.edit_message_text("❌ Неизвестная роль")


async def imagine_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("imagine::"):
        return
    if not query.message:
        await query.answer("Эта кнопка не поддерживается в инлайн-сообщениях.", show_alert=True)
        return
    try:
        parts = data.split("::")
        if len(parts) == 2:
            _, size_part = parts
            # Возьмём промпт из подписи текущего сообщения (до служебной строки генерации)
            if query.message:
                original_caption = (query.message.caption or "")
                prompt = original_caption.split("\n\n🎨", 1)[0].strip()
            else:
                prompt = ""
            seed = None
        elif len(parts) == 3:
            # Обратная совместимость со старыми кнопками: третий параметр мог быть seed, но мы его игнорируем
            _, size_part, _legacy_seed = parts
            if query.message:
                original_caption = (query.message.caption or "")
                prompt = original_caption.split("\n\n🎨", 1)[0].strip()
            else:
                prompt = ""
            seed = None
        elif len(parts) >= 4:
            # Обратная совместимость: старый формат с явным prompt и seed
            _, size_part, prompt, _legacy_seed = parts[:4]
            seed = None
        else:
            raise ValueError("invalid callback format")
        w_str, h_str = size_part.lower().split("x", 1)
        width = max(256, min(1536, int(w_str)))
        height = max(256, min(1536, int(h_str)))
    except Exception as e:
        try:
            await query.edit_message_caption(caption=f"❌ Неверные параметры кнопки, {e}")
        except Exception:
            await query.edit_message_text(text=f"❌ Неверные параметры кнопки, {e}")
        return

    chat_id = query.message.chat.id
    if context_manager.is_generating(chat_id):
        await query.answer("Генерация уже идёт. Пожалуйста, подождите завершения.", show_alert=False)
        return
    context_manager.set_generating(chat_id, True)
    try:
        await query.edit_message_caption(caption=f"{prompt}\n\n🎨 Генерация {width}×{height}…")
        # Валидация и нормализация seed
        seed_value = None
        if seed not in (None, "", "None"):
            try:
                seed_value = int(seed)
            except Exception:
                seed_value = None
        if seed_value is None:
            seed_value = random.randint(1, 2**31 - 1)
        content, _ = await asyncio.to_thread(generate_image, prompt, width, height, seed=seed_value)
        if not content:
            await query.edit_message_caption(caption="❌ Не удалось сгенерировать изображение")
            return
        next_seed = random.randint(1, 2**31 - 1)
        callback_data = f"imagine::{width}x{height}"
        # Лог для отладки длины callback_data
        try:
            logger.debug("regen callback_data=%r len=%d", callback_data, len(callback_data.encode('utf-8')))
        except Exception:
            pass
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Перегенерировать", callback_data=callback_data)],
        ])
        # Отправим новое фото и удалим старое сообщение
        sent = await context.bot.send_photo(chat_id=chat_id, photo=content, caption=f"{prompt}", reply_markup=keyboard)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
    except Exception as e:
        logger.exception(
            "imagine_callback error | chat_id=%s user_id=%s data=%r",
            chat_id if 'chat_id' in locals() else None,
            getattr(query.from_user, 'id', None),
            data,
        )
        try:
            await query.edit_message_caption(caption=f"❌ Ошибка: {str(e)[:300]}")
        except Exception:
            try:
                await query.edit_message_text(text=f"❌ Ошибка: {str(e)[:300]}")
            except Exception:
                pass
    finally:
        context_manager.set_generating(chat_id, False)
