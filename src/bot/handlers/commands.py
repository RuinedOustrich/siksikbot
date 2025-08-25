import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackContext, ContextTypes

from services.context_manager import context_manager
from services.pollinations_service import generate_image
from utils.telegram_utils import show_typing, send_long_message

logger = logging.getLogger(__name__)
import random

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
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
            "/roles - показать роли\n"
            "/setrole <роль> - выбрать роль (storyteller | psychologist | rude)\n"
            "/resetrole - сбросить роль\n"
            "/contextlimit - показать текущий лимит контекста\n"
            "/setcontextlimit <число> - установить лимит контекста\n"
            "/updatecmds - обновить меню команд\n\n"
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
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
            "/roles - показать роли\n"
            "/setrole <роль> - выбрать роль (storyteller | psychologist | rude)\n"
            "/resetrole - сбросить роль\n"
            "/contextlimit - показать текущий лимит контекста\n"
            "/setcontextlimit <число> - установить лимит контекста\n"
            "/updatecmds - обновить меню команд\n\n"
            "💡 **В группах:**\n"
            "• Команды работают без упоминания\n"
            "• Для общения используйте @имя_бота или ответ на мои сообщения\n"
            "• Весь контекст сохраняется\n\n"
            "🎭 **Текущая роль:**\n"
            f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}\n\n"
            "🚫 Рекламные сообщения автоматически удаляются!"
        )
    
    await update.message.reply_text(message_text)


async def reset_context(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context_manager.reset_context(chat_id)
    await update.message.reply_text("✅ История диалога очищена! Начните новый диалог.")


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
        "/prompt — показать текущий системный промпт\n"
        "/setprompt — изменить системный промпт\n"
        "/roles — показать доступные роли\n"
        "/setrole — выбрать роль\n"
        "/resetrole — сбросить роль\n"
        "/contextlimit — показать лимит контекста\n"
        "/setcontextlimit — установить лимит контекста\n"
        "/imagine — сгенерировать изображение\n"
        "/updatecmds — обновить меню команд\n\n"
        "💡 **Особенности:**\n"
        "• Поддержка голосовых сообщений\n"
        "• Анализ изображений\n"
        "• Генерация изображений\n"
        "• Сохранение контекста диалога\n"
        "• Автоматическое удаление рекламы"
    )
    await update.message.reply_text(help_text)


async def roles_command(update: Update, context: CallbackContext):
    roles_text = (
        "🎭 **Доступные роли:**\n\n"
        "**storyteller** — рассказчик историй\n"
        "• Создает увлекательные истории\n"
        "• Использует яркие образы\n"
        "• Развивает сюжетные линии\n\n"
        "**psychologist** — психолог\n"
        "• Анализирует ситуации\n"
        "• Дает советы и рекомендации\n"
        "• Помогает разобраться в чувствах\n\n"
        "**rude** — грубый собеседник\n"
        "• Прямолинейные ответы\n"
        "• Критический подход\n"
        "• Без прикрас\n\n"
        "**astrologer** — астролог\n"
        "• Астрологические прогнозы\n"
        "• Анализ знаков зодиака\n"
        "• Эзотерические советы\n\n"
        "💡 Используйте /setrole <роль> для выбора"
    )
    await update.message.reply_text(roles_text)


async def setrole_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "❌ Укажите роль! Пример: /setrole storyteller\n"
            "Доступные роли: storyteller, psychologist, rude, astrologer"
        )
        return
    
    role = args[0].lower()
    valid_roles = ['storyteller', 'psychologist', 'rude', 'astrologer']
    
    if role not in valid_roles:
        await update.message.reply_text(
            f"❌ Неизвестная роль: {role}\n"
            f"Доступные роли: {', '.join(valid_roles)}"
        )
        return
    
    context_manager.set_role(chat_id, role)
    await update.message.reply_text(f"✅ Роль установлена: {role}")


async def resetrole_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context_manager.reset_role(chat_id)
    await update.message.reply_text("✅ Роль сброшена к значению по умолчанию")


async def prompt_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    current_prompt = context_manager.get_system_prompt(chat_id)
    await update.message.reply_text(f"🎭 **Текущий системный промпт:**\n\n{current_prompt}")


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


async def resetprompt_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context_manager.reset_system_prompt(chat_id)
    await update.message.reply_text("✅ Системный промпт сброшен к значению по умолчанию")


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
            BotCommand("setrole", "🎭 Выбрать роль (storyteller|psychologist|astrologer|rude)"),
            BotCommand("resetrole", "🎭 Сбросить роль к умолчанию"),
            BotCommand("contextlimit", "📏 Показать текущий лимит контекста"),
            BotCommand("setcontextlimit", "✏️ Установить лимит контекста (напр. 30)"),
            BotCommand("imagine", "🖼️ Сгенерировать изображение по описанию"),
        ]
        
        await application.bot.set_my_commands(commands)
        await update.message.reply_text("✅ Меню команд обновлено!")
    except Exception as e:
        logger.error(f"Ошибка обновления команд: {e}")
        await update.message.reply_text("❌ Ошибка обновления команд")


async def contextlimit_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    limit = context_manager.get_context_limit(chat_id)
    await update.message.reply_text(f"📏 Текущий лимит контекста: {limit} сообщений")


async def setcontextlimit_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "❌ Укажите лимит! Пример: /setcontextlimit 30"
        )
        return
    
    try:
        limit = int(args[0])
        if limit < 1 or limit > 100:
            await update.message.reply_text("❌ Лимит должен быть от 1 до 100")
            return
        
        context_manager.set_context_limit(chat_id, limit)
        await update.message.reply_text(f"✅ Лимит контекста установлен: {limit} сообщений")
    except ValueError:
        await update.message.reply_text("❌ Лимит должен быть числом!")


async def imagine_command(update: Update, context: CallbackContext):
    """Генерация изображения по описанию: /imagine <prompt> [--w 1024 --h 1024]"""
    chat_id = update.effective_chat.id
    if context_manager.is_generating(chat_id):
        await update.message.reply_text("⏳ Подождите, я ещё выполняю предыдущую задачу…")
        return

    if not context.args:
        await update.message.reply_text(
            "🖼️ Использование: /imagine <описание> [--w 1024 --h 1024]\nПример: /imagine кот космонавт --w 768 --h 768"
        )
        return

    # Парсим простые флаги размеров
    seed = random.randint(0, 2**32-1)
    args = context.args
    width, height = 1024, 1024
    prompt_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--w" and i + 1 < len(args):
            try:
                width = max(256, min(1536, int(args[i+1])))
                i += 2
                continue
            except Exception:
                pass
        if args[i] == "--h" and i + 1 < len(args):
            try:
                height = max(256, min(1536, int(args[i+1])))
                i += 2
                continue
            except Exception:
                pass
        prompt_parts.append(args[i])
        i += 1
    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        await update.message.reply_text("❌ Опишите, что нужно сгенерировать")
        return

    context_manager.set_generating(chat_id, True)
    status = await update.message.reply_text("🎨 Генерирую изображение…")
    try:
        content, url = await asyncio.to_thread(generate_image, prompt, width, height, seed = seed)
        if not content:
            await status.edit_text("❌ Не удалось сгенерировать изображение")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Перегенерировать", callback_data=f"imagine::{width}x{height}::{seed}")],
        ])
        # Отправляем без источника в подписи — по просьбе пользователя
        await context.bot.send_photo(chat_id=chat_id, photo=content, caption=f"{prompt}", reply_markup=keyboard)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=status.message_id)
        except Exception:
            pass
    except Exception as e:
        logger.exception("imagine_command error")
        await status.edit_text(f"❌ Ошибка: {str(e)[:300]}")
    finally:
        context_manager.set_generating(chat_id, False)
