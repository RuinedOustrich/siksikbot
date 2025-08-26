import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackContext

from services.context_manager import context_manager
from services.pollinations_service import generate_image_async, auto_analyze_generated_image
from utils.telegram_utils import show_typing
from utils.decorators import handle_errors, track_performance
from utils.health_check import get_health_status
from config.settings import settings

logger = logging.getLogger(__name__)
import random

@handle_errors
@track_performance
async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user = update.effective_user
    
    logger.info(f"Команда /start вызвана пользователем {user.id} в чате {chat_id} (тип: {chat_type})")
    logger.info(f"Отправляю приветственное сообщение...")
    
    context_manager.init_context(chat_id)
    
    current_prompt = context_manager.get_system_prompt(chat_id)
    # Разные сообщения для личных чатов и групп
    if update.effective_chat.type == ChatType.PRIVATE:
        message_text = (
            "🤖 Привет! Я бот СикСик.\n"
            "Задай вопрос, отправь голосовое или изображение!\n\n"
            "⚙️ **Команды:**\n"
            "/start - начать диалог\n"
            "/reset - очистить историю диалога\n"
            "/help - показать справку\n"
            "/roles - показать роли\n"
            "/imagine - сгенерировать изображение\n"    
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
            "/resetprompt - сбросить промпт к значению по умолчанию\n"
            "/updatecmds - обновить меню команд\n"
            "/settings - настройки чата\n"
            "/stop - принудительно остановить все операции\n"
            "/health - показать состояние бота\n\n"
            "🎭 **Текущая роль:**\n"
            f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}\n\n"
            "🚫 Рекламные сообщения автоматически удаляются!"
        )
    else:
        message_text = (
            "🤖 Привет! Я бот СикСик.\n"
            "Задай вопрос, отправь голосовое или изображение!\n\n"
            "⚙️ **Команды (работают везде):**\n"
            "/start - начать диалог\n"
            "/reset - очистить историю диалога\n"
            "/help - показать справку\n"
            "/roles - показать роли\n"
            "/imagine - сгенерировать изображение\n"    
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
            "/resetprompt - сбросить промпт к значению по умолчанию\n"
            "/updatecmds - обновить меню команд\n"
            "/health - показать состояние бота\n\n"
            "💡 **В группах:**\n"
            "• Команды работают без упоминания\n"
            "• Для общения используйте @имя_бота или ответ на мои сообщения\n"
            "• Весь контекст сохраняется\n\n"
            "🎭 **Текущая роль:**\n"
            f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}\n\n"
            "🚫 Рекламные сообщения автоматически удаляются!"
        )
    
    await update.message.reply_text(message_text)


@handle_errors
async def reset_context(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context_manager.reset_context(chat_id)
    await update.message.reply_text("✅ История диалога очищена! Начните новый диалог.")


@handle_errors
async def stop_command(update: Update, context: CallbackContext):
    """Команда для принудительной остановки всех операций"""
    chat_id = update.effective_chat.id
    
    # Проверяем, есть ли активные операции
    has_active_operations = (
        context_manager.is_generating(chat_id, "image") or
        context_manager.is_generating(chat_id, "text") or
        context_manager.is_generating(chat_id, "voice") or
        context_manager.has_user_state(chat_id, "imagine")
    )
    
    if not has_active_operations:
        await update.message.reply_text("ℹ️ Нет активных операций для остановки.")
        return
    
    # Принудительно останавливаем все операции
    context_manager.force_stop_all_operations(chat_id)
    
    stop_msg = await update.message.reply_text(
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


@handle_errors
async def settings_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    s = context_manager.get_settings(chat_id)
    verb = s.get("verbosity", "normal")
    lang = s.get("lang", "auto")
    group_mode = s.get("group_mode", "mention_or_reply")
    context_limit = s.get("context_limit", context_manager.get_context_limit(chat_id))
    
    # Получаем состояние автоанализа
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
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@handle_errors
async def help_command(update: Update, context: CallbackContext):
    help_text = (
        "🆘 Справка по боту:\n\n"
        "Поддерживаемые типы сообщений:\n"
        "- Текстовые запросы\n"
        "- Голосовые сообщения\n"
        "- Изображения с описанием\n\n"
        "🔧 Доступные команды:\n"
        "/start — начать диалог\n"
        "/reset — очистить историю диалога\n"
        "/help — показать эту справку\n"
        "/roles — показать доступные роли\n"
        "/imagine — сгенерировать изображение\n"
        "/prompt — показать текущий системный промпт\n"
        "/setprompt — изменить системный промпт\n"
        "/resetprompt - сбросить промпт к значению по умолчанию\n"
        "/updatecmds — обновить меню команд\n"
        "/settings — меню настроек\n"
        "/stop — принудительно остановить все операции\n"
        "/health — показать состояние бота\n\n"
        "💡 **Особенности:**\n"
        "• Поддержка голосовых сообщений\n"
        "• Анализ изображений\n"
        "• Генерация изображений\n"
        "• Сохранение контекста диалога\n"
        "• Автоматическое удаление рекламы"
    )
    await update.message.reply_text(help_text)


@handle_errors
async def roles_command(update: Update, context: CallbackContext):
    roles = context_manager.get_available_roles()
    keyboard = [[InlineKeyboardButton(role.capitalize(), callback_data=f"role::{role}")] for role in roles]
    keyboard.append([InlineKeyboardButton("Сбросить роль", callback_data="role::reset")])
    await update.message.reply_text(
        "🎭 Выберите роль:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@handle_errors
async def prompt_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    current_prompt = context_manager.get_system_prompt(chat_id)
    await update.message.reply_text(f"🎭 **Текущий системный промпт:**\n\n{current_prompt}")


@handle_errors
async def setprompt_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "❌ Укажите новый промпт! Пример: /setprompt Ты полезный ассистент"
        )
        return
    
    new_prompt = ' '.join(args)
    context_manager.set_system_prompt(chat_id, new_prompt)
    await update.message.reply_text(f"✅ Системный промпт обновлен:\n\n{new_prompt}")


@handle_errors
async def resetprompt_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context_manager.reset_system_prompt(chat_id)
    await update.message.reply_text("✅ Системный промпт сброшен к значению по умолчанию")


@handle_errors
async def update_commands_command(update: Update, context: CallbackContext):
    from telegram import BotCommand
    from telegram.ext import Application
    
    try:
        application = context.application
        commands = [
            BotCommand("start", "🚀 Начать диалог с ботом"),
            BotCommand("help", "❓ Показать справку по командам"),
            BotCommand("reset", "🔄 Очистить историю диалога"),
            BotCommand("prompt", "🎭 Показать текущий системный промпт"),
            BotCommand("setprompt", "✏️ Изменить системный промпт"),
            BotCommand("resetprompt", "🔄 Сбросить промпт к значению по умолчанию"),
            BotCommand("roles", "🎭 Показать доступные роли"),
            BotCommand("settings", "⚙️ Открыть меню настроек"),
            BotCommand("imagine", "🖼️ Сгенерировать изображение по описанию"),
            BotCommand("health", "🏥 Показать состояние бота")
        ]
        
        await application.bot.set_my_commands(commands)
        await update.message.reply_text("✅ Меню команд обновлено!")
    except Exception as e:
        logger.error(f"Ошибка обновления команд: {e}")
        err_msg = await update.message.reply_text("❌ Ошибка обновления команд")
        context_manager.add_cleanup_message(update.effective_chat.id, err_msg.message_id)



@handle_errors
@track_performance
async def imagine_command(update: Update, context: CallbackContext):
    """Интерактивная генерация изображения с выбором размера и стиля"""
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, chat_id, min_interval=2.0):
        logger.info(f"Rate limit заблокирован для пользователя {user.id} в чате {chat_id} (imagine)")
        await update.message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        return
    
    if context_manager.is_generating(chat_id, "image"):
        await update.message.reply_text("⏳ Подождите, я ещё генерирую изображение…")
        return
    
    # Записываем запрос для rate limiting
    from utils.rate_limiter import rate_limiter
    rate_limiter.record_request(user.id, chat_id)

    # Если есть аргументы, используем старый режим (быстрая генерация)
    if context.args:
        await _imagine_quick_mode(update, context)
        return
    
    # Новый интерактивный режим - выбор размера
    await _show_size_selection(update, context)


async def _show_size_selection(update: Update, context: CallbackContext):
    """Показывает меню выбора размера изображения"""
    chat_id = update.effective_chat.id
    
    # Создаем кнопки для размеров (по 2 в ряд)
    keyboard = []
    presets = list(settings.image_size_presets.items())
    
    for i in range(0, len(presets), 2):
        row = []
        for j in range(2):
            if i + j < len(presets):
                key, preset = presets[i + j]
                emoji = preset["emoji"]
                name = preset["name"]
                row.append(InlineKeyboardButton(
                    f"{emoji} {name}", 
                    callback_data=f"imagine_size::{key}"
                ))
        keyboard.append(row)
    
    # Добавляем кнопку для пользовательского размера
    keyboard.append([InlineKeyboardButton("⚙️ Свой размер", callback_data="imagine_size::custom")])
    
    await update.message.reply_text(
        "🖼️ **Генерация изображения**\n\nВыбери размер:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _show_style_selection(chat_id: int, bot, size_key: str, width: int, height: int):
    """Показывает меню выбора стиля изображения"""
    
    # Сохраняем выбранный размер в состоянии
    context_manager.set_user_state(chat_id, "imagine", {
        "step": "style_selection",
        "size_key": size_key,
        "width": width,
        "height": height
    })
    
    # Создаем кнопки для стилей (по 2 в ряд)
    keyboard = []
    styles = list(settings.image_style_presets.items())
    
    for i in range(0, len(styles), 2):
        row = []
        for j in range(2):
            if i + j < len(styles):
                key, style = styles[i + j]
                emoji = style["emoji"]
                name = style["name"]
                row.append(InlineKeyboardButton(
                    f"{emoji} {name}", 
                    callback_data=f"imagine_style::{key}"
                ))
        keyboard.append(row)
    
    # Добавляем кнопку "Пропустить стиль"
    keyboard.append([InlineKeyboardButton("⏭️ Без стиля", callback_data="imagine_style::none")])
    
    size_info = settings.image_size_presets[size_key]
    text = f"🎨 **Выбери стиль (необязательно):**\n\nРазмер: {size_info['emoji']} {size_info['name']} ({width}×{height})"
    
    return text, InlineKeyboardMarkup(keyboard)


async def _request_description(chat_id: int, bot, size_key: str, width: int, height: int, style_key: str = None):
    """Запрашивает описание изображения от пользователя"""
    
    # Обновляем состояние
    state_data = {
        "step": "waiting_description",
        "size_key": size_key,
        "width": width,
        "height": height,
        "style_key": style_key
    }
    context_manager.set_user_state(chat_id, "imagine", state_data)
    
    # Формируем текст с информацией о выбранных параметрах
    size_info = settings.image_size_presets[size_key]
    text = f"📝 **Опиши что нарисовать:**\n\n"
    text += f"Размер: {size_info['emoji']} {size_info['name']} ({width}×{height})\n"
    
    if style_key and style_key != "none":
        style_info = settings.image_style_presets[style_key]
        text += f"Стиль: {style_info['emoji']} {style_info['name']}\n"
    
    text += "\n💡 Напиши описание изображения..."
    
    return text


async def _imagine_quick_mode(update: Update, context: CallbackContext):
    """Быстрый режим генерации с аргументами команды (старый способ)"""
    chat_id = update.effective_chat.id
    
    # Парсим аргументы (старая логика)
    seed = random.randint(0, 2**32-1)
    args = context.args[:]
    width, height = 1024, 1024
    prompt_parts = []
    i = 0
    
    # Проверяем пресеты в первом аргументе
    if args and args[0].lower() in settings.image_size_presets:
        preset = settings.image_size_presets[args[0].lower()]
        width, height = preset["width"], preset["height"]
        args = args[1:]  # убираем пресет из аргументов
    
    # Парсим флаги размеров и seed
    while i < len(args):
        if args[i] == "--w" and i + 1 < len(args):
            try:
                width = max(256, min(1920, int(args[i+1])))
                i += 2
                continue
            except Exception:
                pass
        elif args[i] == "--h" and i + 1 < len(args):
            try:
                height = max(256, min(1920, int(args[i+1])))
                i += 2
                continue
            except Exception:
                pass
        elif args[i].lower().startswith('seed:'):
            try:
                seed = int(args[i].split(':', 1)[1])
                i += 1
                continue
            except ValueError:
                pass
        
        prompt_parts.append(args[i])
        i += 1
    
    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        # Показываем справку по размерам
        presets_text = "🖼️ **Генерация изображений**\n\n"
        presets_text += "**Использование:** `/imagine [размер] описание [seed:число]`\n\n"
        presets_text += "📐 **Доступные размеры:**\n"
        for key, preset in settings.image_size_presets.items():
            presets_text += f"• `{key}` - {preset['name']} ({preset['width']}×{preset['height']})\n"
        presets_text += f"• `--w XXX --h XXX` - точные размеры\n\n"
        presets_text += "**Примеры:**\n"
        presets_text += "• `/imagine красивый закат`\n"
        presets_text += "• `/imagine portrait кот в шляпе`\n"
        presets_text += "• `/imagine wallpaper горный пейзаж`\n"
        presets_text += "• `/imagine --w 512 --h 768 робот seed:12345`"
        
        await update.message.reply_text(presets_text, parse_mode=ParseMode.MARKDOWN)
        return

    # Генерируем изображение
    await _generate_image(chat_id, context.bot, prompt, width, height, seed)


async def _generate_image(chat_id: int, bot, prompt: str, width: int, height: int, seed: int = None, style_key: str = None, description_message_id: int = None):
    """Основная функция генерации изображения"""
    
    if seed is None:
        seed = random.randint(0, 2**32-1)
    
    # Добавляем стиль к промпту если выбран
    final_prompt = prompt
    if style_key and style_key in settings.image_style_presets:
        style_info = settings.image_style_presets[style_key]
        final_prompt = f"{prompt}, {style_info['prompt']}"
    
    context_manager.set_generating(chat_id, True, "image")
    status = await bot.send_message(chat_id, "🎨 Генерирую изображение…")
    
    try:
        # Проверяем принудительную остановку перед началом
        if context_manager.is_force_stop_requested(chat_id):
            stop_msg = await status.edit_text("🛑 Генерация остановлена пользователем")
            context_manager.add_cleanup_message(chat_id, stop_msg.message_id)
            context_manager.clear_force_stop(chat_id)
            return

        # Создаем задачу для возможности отмены
        import asyncio
        task = asyncio.create_task(generate_image_async(final_prompt, width, height, seed=seed))

        # Ждем с периодической проверкой остановки
        while not task.done():
            # Проверяем остановку каждые 0.05 секунды для более быстрой реакции
            if context_manager.is_force_stop_requested(chat_id):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                stop_msg = await status.edit_text("🛑 Генерация остановлена пользователем")
                context_manager.add_cleanup_message(chat_id, stop_msg.message_id)
                context_manager.clear_force_stop(chat_id)
                return

            await asyncio.sleep(0.05)

        content, url = await task
        
        # Проверяем принудительную остановку после генерации
        if context_manager.is_force_stop_requested(chat_id):
            stop_msg = await status.edit_text("🛑 Генерация остановлена пользователем")
            context_manager.add_cleanup_message(chat_id, stop_msg.message_id)
            context_manager.clear_force_stop(chat_id)
            return
            
        if not content:
            if url == "rate_limit":
                await status.edit_text("⚠️ Превышен лимит запросов к сервису генерации. Попробуйте через несколько минут.")
            else:
                await status.edit_text("❌ Не удалось сгенерировать изображение")
            context_manager.add_cleanup_message(chat_id, status.message_id)
            return
        
        # Автоматический анализ сгенерированного изображения для контекста
        if context_manager.is_auto_analyze_enabled(chat_id):
            try:
                analysis = await auto_analyze_generated_image(
                    image_content=content, 
                    prompt=final_prompt, 
                    token=settings.pollinations_token
                )
                if analysis:
                    # Сохраняем анализ в контекст как системное сообщение об изображении
                    context_manager.add_image_context(chat_id, analysis)
                    logger.debug(f"Автоанализ сгенерированного изображения сохранен в контекст для чата {chat_id}")
            except Exception as e:
                logger.warning(f"Не удалось выполнить автоанализ изображения: {e}")
        
        # Создаем кнопки
        keyboard = [
            [InlineKeyboardButton("🔄 Перегенерировать", callback_data=f"imagine::{width}x{height}")],
            [InlineKeyboardButton("🎨 Новое изображение", callback_data="imagine_new")]
        ]
        
        # Отправляем изображение
        await bot.send_photo(
            chat_id=chat_id, 
            photo=content, 
            caption=f"{prompt}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status.message_id)
        except Exception:
            pass
        
        # Удаляем накопленные предупреждения/ошибки после успешной генерации
        for mid in context_manager.consume_cleanup_messages(chat_id):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
        
        # Удаляем сообщение с описанием после успешной генерации
        if description_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=description_message_id)
                logger.info(f"Удалено сообщение с описанием изображения: {description_message_id}")
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение с описанием {description_message_id}: {e}")
            
        # Очищаем состояние пользователя после успешной генерации
        context_manager.clear_user_state(chat_id, "imagine")
        
    except Exception as e:
        logger.exception("_generate_image error")
        await status.edit_text(f"❌ Ошибка: {str(e)[:300]}")
        
        # Удаляем сообщение с описанием даже в случае ошибки
        if description_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=description_message_id)
                logger.info(f"Удалено сообщение с описанием изображения после ошибки: {description_message_id}")
            except Exception as delete_error:
                logger.warning(f"Не удалось удалить сообщение с описанием {description_message_id} после ошибки: {delete_error}")
    finally:
        context_manager.set_generating(chat_id, False, "image")



@handle_errors
async def health_command(update: Update, context: CallbackContext):
    """Команда для проверки состояния бота"""
    health = get_health_status()
    
    if health["status"] == "error":
        err_msg = await update.message.reply_text(f"❌ Ошибка получения статуса: {health.get('error', 'Неизвестная ошибка')}")
        context_manager.add_cleanup_message(update.effective_chat.id, err_msg.message_id)
        return
    
    message = (
        f"🏥 **Статус бота:** {health['status']}\n"
        f"⏱️ **Время работы:** {health['uptime_hours']:.1f} часов\n"
        f"💾 **Память:** {health['memory_usage_percent']:.1f}% использовано\n"
        f"💿 **Диск:** {health['disk_usage_percent']:.1f}% использовано\n"
        f"💬 **Активных чатов:** {health['active_contexts']}\n"
        f"📝 **Всего сообщений:** {health['total_messages']}\n"
        f"📊 **Запросов:** {health['request_count']}\n"
        f"❌ **Ошибок:** {health['error_count']} ({health['error_rate_percent']:.1f}%)"
    )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)



