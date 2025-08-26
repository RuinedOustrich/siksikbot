import logging
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from services.context_manager import context_manager
from services.pollinations_service import generate_image_async, auto_analyze_generated_image
from utils.decorators import handle_errors
from config.settings import settings

logger = logging.getLogger(__name__)


async def _safe_edit_query_message(query, text, reply_markup=None):
    try:
        m = query.message
        if m and (m.caption is not None or m.photo or m.document or m.video):
            return await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        return await query.edit_message_text(text=text, reply_markup=reply_markup)
    except Exception:
        return None


@handle_errors
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


@handle_errors
async def settings_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("settings::"):
        return
    chat_id = query.message.chat.id

    s = context_manager.get_settings(chat_id)
    action = data.split("::", 1)[1]

    if action == "toggle_verbosity":
        order = ["short", "normal", "long"]
        cur = s.get("verbosity", "normal")
        nxt = order[(order.index(cur) + 1) % len(order)]
        s = context_manager.update_settings(chat_id, verbosity=nxt)
    elif action == "toggle_lang":
        order = ["auto", "ru", "en"]
        cur = s.get("lang", "auto")
        nxt = order[(order.index(cur) + 1) % len(order)]
        s = context_manager.update_settings(chat_id, lang=nxt)
    elif action == "toggle_group_mode":
    # Доступны 2 режима: отвечать при упоминании или ответе, либо всегда
        order = ["mention_or_reply", "always"]
        cur = s.get("group_mode", "mention_or_reply")
        nxt = order[(order.index(cur) + 1) % len(order)]
        s = context_manager.update_settings(chat_id, group_mode=nxt)
    elif action == "context_limit":
        # Крутим значения 20/40/60/100
        order = [20, 40, 60, 100]
        cur = int(s.get("context_limit", context_manager.get_context_limit(chat_id)))
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else context_manager.get_context_limit(chat_id)
        s = context_manager.update_settings(chat_id, context_limit=nxt)
    elif action == "toggle_auto_analyze":
        # Переключаем автоанализ изображений
        context_manager.toggle_auto_analyze(chat_id)
    else:
        return

    verb = s.get("verbosity", "normal")
    lang = s.get("lang", "auto")
    group_mode = s.get("group_mode", "mention_or_reply")
    context_limit = s.get("context_limit", context_manager.get_context_limit(chat_id))
    
    # Получаем актуальное состояние автоанализа
    auto_analyze_enabled = context_manager.is_auto_analyze_enabled(chat_id)
    auto_analyze_text = "Включен" if auto_analyze_enabled else "Отключен"

    keyboard = [
        [InlineKeyboardButton(f"Детализация: {verb}", callback_data="settings::toggle_verbosity")],
        [InlineKeyboardButton(f"Язык: {lang}", callback_data="settings::toggle_lang")],
        [InlineKeyboardButton(f"Режим в группе: {group_mode}", callback_data="settings::toggle_group_mode")],
        [InlineKeyboardButton(f"Лимит контекста: {context_limit}", callback_data="settings::context_limit")],
        [InlineKeyboardButton(f"Автоанализ изображений: {auto_analyze_text}", callback_data="settings::toggle_auto_analyze")],
    ]

    text = (
        "⚙️ Настройки чата\n\n"
        f"• Детализация: {verb}\n"
        f"• Язык: {lang}\n"
        f"• Режим в группе: {group_mode}\n"
        f"• Лимит контекста: {context_limit}\n"
        f"• Автоанализ изображений: {auto_analyze_text}\n\n"
        "Нажмите на пункт, чтобы переключить."
    )

    await _safe_edit_query_message(query, text, InlineKeyboardMarkup(keyboard))


@handle_errors
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
        chat_id = query.message.chat.id if query.message else None
        try:
            await query.edit_message_caption(caption=f"❌ Неверные параметры кнопки, {e}")
            if chat_id and query.message:
                context_manager.add_cleanup_message(chat_id, query.message.message_id)
        except Exception:
            await query.edit_message_text(text=f"❌ Неверные параметры кнопки, {e}")
            if chat_id and query.message:
                context_manager.add_cleanup_message(chat_id, query.message.message_id)
        return

    chat_id = query.message.chat.id
    if context_manager.is_generating(chat_id, "image"):
        await query.answer("Генерация уже идёт. Пожалуйста, подождите завершения.", show_alert=False)
        return
    context_manager.set_generating(chat_id, True, "image")
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
        # Проверяем принудительную остановку перед генерацией
        if context_manager.is_force_stop_requested(chat_id):
            await query.edit_message_caption(caption="🛑 Генерация остановлена пользователем")
            context_manager.add_cleanup_message(chat_id, query.message.message_id)
            context_manager.clear_force_stop(chat_id)
            return

        content, _ = await generate_image_async(prompt, width, height, seed=seed_value)
        
        # Проверяем принудительную остановку после генерации
        if context_manager.is_force_stop_requested(chat_id):
            await query.edit_message_caption(caption="🛑 Генерация остановлена пользователем")
            context_manager.add_cleanup_message(chat_id, query.message.message_id)
            context_manager.clear_force_stop(chat_id)
            return
            
        if not content:
            await query.edit_message_caption(caption="❌ Не удалось сгенерировать изображение")
            # Добавляем сообщение об ошибке в список для удаления при следующем успешном ответе
            context_manager.add_cleanup_message(chat_id, query.message.message_id)
            return
        
        # Автоматический анализ сгенерированного изображения для контекста
        if context_manager.is_auto_analyze_enabled(chat_id):
            try:
                analysis = await auto_analyze_generated_image(
                    image_content=content, 
                    prompt=prompt, 
                    token=settings.pollinations_token
                )
                if analysis:
                    # Сохраняем анализ в контекст как системное сообщение об изображении
                    context_manager.add_image_context(chat_id, analysis)
                    logger.debug(f"Автоанализ перегенерированного изображения сохранен в контекст для чата {chat_id}")
            except Exception as e:
                logger.warning(f"Не удалось выполнить автоанализ перегенерированного изображения: {e}")
        
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
        
        # Удаляем накопленные предупреждения/ошибки после успешной перегенерации
        for mid in context_manager.consume_cleanup_messages(chat_id):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
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
            # Добавляем отредактированное сообщение об ошибке в список для удаления
            if 'chat_id' in locals() and chat_id and query.message:
                context_manager.add_cleanup_message(chat_id, query.message.message_id)
        except Exception:
            try:
                await query.edit_message_text(text=f"❌ Ошибка: {str(e)[:300]}")
                # Добавляем отредактированное сообщение об ошибке в список для удаления
                if 'chat_id' in locals() and chat_id and query.message:
                    context_manager.add_cleanup_message(chat_id, query.message.message_id)
            except Exception:
                pass
    finally:
        context_manager.set_generating(chat_id, False, "image")


@handle_errors
async def imagine_size_callback(update: Update, context: CallbackContext):
    """Обработчик выбора размера изображения"""
    query = update.callback_query
    chat_id = query.message.chat.id
    
    try:
        # Извлекаем выбранный размер
        size_key = query.data.split("::", 1)[1]
        
        if size_key == "custom":
            # TODO: Реализовать ввод пользовательского размера
            await query.edit_message_text("🚧 Пользовательские размеры пока не поддерживаются. Выберите из предустановленных.")
            return
        
        if size_key not in settings.image_size_presets:
            await query.edit_message_text("❌ Неверный размер")
            return
        
        preset = settings.image_size_presets[size_key]
        width, height = preset["width"], preset["height"]
        
        # Показываем выбор стиля
        from bot.handlers.commands import _show_style_selection
        text, keyboard = await _show_style_selection(chat_id, context.bot, size_key, width, height)
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        await query.answer()
        
    except Exception as e:
        logger.exception("imagine_size_callback error")
        await query.edit_message_text("❌ Ошибка обработки выбора размера")


@handle_errors
async def imagine_style_callback(update: Update, context: CallbackContext):
    """Обработчик выбора стиля изображения"""
    query = update.callback_query
    chat_id = query.message.chat.id
    
    try:
        # Извлекаем выбранный стиль
        style_key = query.data.split("::", 1)[1]
        
        # Получаем сохраненное состояние
        state = context_manager.get_user_state(chat_id, "imagine")
        if not state:
            await query.edit_message_text("❌ Сессия истекла. Начните заново с /imagine")
            return
        
        size_key = state["size_key"]
        width = state["width"]
        height = state["height"]
        
        # Запрашиваем описание
        from bot.handlers.commands import _request_description
        text = await _request_description(chat_id, context.bot, size_key, width, height, style_key)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        await query.answer()
        
    except Exception as e:
        logger.exception("imagine_style_callback error")
        await query.edit_message_text("❌ Ошибка обработки выбора стиля")


@handle_errors
async def imagine_new_callback(update: Update, context: CallbackContext):
    """Обработчик кнопки 'Новое изображение'"""
    query = update.callback_query
    chat_id = query.message.chat.id
    
    try:
        # Показываем выбор размера для нового изображения
        from bot.handlers.commands import _show_size_selection
        
        # Создаем фейковый update для _show_size_selection
        class FakeMessage:
            def __init__(self, chat_id, bot):
                self.chat_id = chat_id
                self.bot = bot
                
            async def reply_text(self, text, reply_markup=None, parse_mode=None):
                return await self.bot.send_message(
                    self.chat_id, text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
        
        class FakeChat:
            def __init__(self, chat_id):
                self.id = chat_id
        
        class FakeUpdate:
            def __init__(self, chat_id, bot):
                self.message = FakeMessage(chat_id, bot)
                self.effective_chat = FakeChat(chat_id)
        
        fake_update = FakeUpdate(chat_id, context.bot)
        await _show_size_selection(fake_update, context)
        
        await query.answer("🎨 Создаем новое изображение!")
        
    except Exception as e:
        logger.exception("imagine_new_callback error")
        await query.answer("❌ Ошибка создания нового изображения", show_alert=True)


@handle_errors
async def force_stop_callback(update: Update, context: CallbackContext):
    """Обработчик кнопки принудительной остановки"""
    query = update.callback_query
    chat_id = query.message.chat.id
    
    try:
        # Проверяем, есть ли активные операции
        has_active_operations = (
            context_manager.is_generating(chat_id, "image") or
            context_manager.is_generating(chat_id, "text") or
            context_manager.is_generating(chat_id, "voice") or
            context_manager.has_user_state(chat_id, "imagine")
        )
        
        if not has_active_operations:
            await query.answer("ℹ️ Нет активных операций для остановки", show_alert=True)
            return
        
        # Принудительно останавливаем все операции
        context_manager.force_stop_all_operations(chat_id)
        
        stop_msg = await query.edit_message_text(
            "🛑 **Все операции принудительно остановлены!**\n\n"
            "• Генерация изображений остановлена\n"
            "• Обработка текста остановлена\n"
            "• Обработка голоса остановлена\n"
            "• Все состояния очищены\n\n"
            "Теперь можете начать новые операции.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Добавляем сообщение об остановке в список для очистки
        context_manager.add_cleanup_message(chat_id, stop_msg.message_id)
        
        await query.answer("🛑 Все операции остановлены!")
        
    except Exception as e:
        logger.exception("force_stop_callback error")
        await query.answer("❌ Ошибка остановки операций", show_alert=True)
