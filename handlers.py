import os
import logging
import time
import asyncio
import re
import shutil
import subprocess
import tempfile
import uuid
from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackContext, ContextTypes

from context_manager import context_manager
from pollinations_service import send_to_pollinations, transcribe_audio, analyze_image
from telegram_utils import show_typing, send_long_message, delete_advertisement


logger = logging.getLogger(__name__)


async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user = update.effective_user
    
    logger.info(f"Команда /start вызвана пользователем {user.id} в чате {chat_id} (тип: {chat_type})")
    
    context_manager.init_context(chat_id)
    
    current_prompt = context_manager.get_system_prompt()
    # Разные сообщения для личных чатов и групп
    if update.effective_chat.type in [update.effective_chat.PRIVATE]:
        message_text = (
            "🤖 Привет! Я бот на базе Pollinations.AI.\n"
            "Задай вопрос, отправь голосовое или изображение!\n\n"
            "⚙️ **Команды:**\n"
            "/start - начать диалог\n"
            "/reset - очистить историю диалога\n"
            "/help - показать справку\n"
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
            "/updatecmds - обновить меню команд\n\n"
            "🎭 **Текущая роль:**\n"
            f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}\n\n"
            "🚫 Рекламные сообщения автоматически удаляются!"
        )
    else:
        message_text = (
            "🤖 Привет! Я бот на базе Pollinations.AI.\n"
            "Задай вопрос, отправь голосовое или изображение!\n\n"
            "⚙️ **Команды (работают везде):**\n"
            "/start - начать диалог\n"
            "/reset - очистить историю диалога\n"
            "/help - показать справку\n"
            "/prompt - показать текущий системный промпт\n"
            "/setprompt - изменить системный промпт\n"
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
        "/start - начать диалог\n"
        "/reset - очистить историю\n"
        "/help - эта справка\n"
        "/prompt - показать текущий системный промпт\n"
        "/setprompt - установить новый системный промпт\n"
        "/resetprompt - сбросить промпт к значению по умолчанию\n"
        "/updatecmds - обновить меню команд\n\n"
        "ℹ️ **В группах:**\n"
        "• Команды работают везде (без упоминания)\n"
        "• Для общения используйте @имя_бота или ответ на мои сообщения\n"
        "• Бот сохраняет весь контекст диалога (все сообщения в чате)\n"
        "🚫 Рекламные сообщения автоматически удаляются!"
    )
    await update.message.reply_text(help_text)


async def handle_message(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, min_interval=1.0):
        await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        return

    is_ad = await delete_advertisement(update, context)
    if is_ad:
        return

    user_message = message.text or message.caption or ""

    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        bot_username = context.bot.username.lower()
        mentioned = False

        if f"@{bot_username}" in user_message.lower():
            mentioned = True
            user_message = re.sub(f"@{bot_username}", "", user_message, flags=re.IGNORECASE).strip()

        if not mentioned and message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                mentioned = True

        # Сохраняем сообщение даже если нет упоминания

    full_name = user.first_name or (user.username if user.username else str(user.id))
    author = {"id": user.id, "name": full_name, "username": user.username}
    context_manager.add_message(chat_id, "user", user_message, author=author)

    # Если в группе нет упоминания и это не ответ на бота — не генерируем ответ
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and not mentioned:
        logger.info(f"Сообщение в группе {chat_id} сохранено, но не требует ответа")
        return

    pollinations_token = os.getenv("POLLINATIONS_TOKEN")
    if not pollinations_token:
        logger.error("POLLINATIONS_TOKEN не установлен!")
        await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
        return

    context_manager.set_generating(chat_id, True)
    typing_task = asyncio.create_task(show_typing(context, chat_id))

    status_message = None
    try:
        messages = context_manager.build_api_messages(chat_id)
        status_message = await message.reply_text("💭 Думаю...")

        start_time = time.time()
        ai_response = await asyncio.to_thread(
            send_to_pollinations,
            messages=messages,
            token=pollinations_token
        )
        logger.info(f"Ответ получен за {time.time() - start_time:.2f} сек")

        try:
            if status_message:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=status_message.message_id
                )
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        if ai_response:
            if len(ai_response) > 4000:
                await send_long_message(context, chat_id, ai_response, message.message_id)
            else:
                await message.reply_text(
                    ai_response,
                    reply_to_message_id=message.message_id,
                    parse_mode=ParseMode.MARKDOWN
                )

            context_manager.add_message(chat_id, "assistant", ai_response)
        else:
            await message.reply_text("❌ Не удалось получить ответ от API")

    except Exception as e:
        logger.exception("Ошибка в handle_message")
        if status_message:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ Ошибка: {str(e)[:1000]}"
                )
            except Exception:
                await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
        else:
            await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()


async def handle_voice(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user_id, min_interval=2.0):
        await message.reply_text("⚠️ Слишком много голосовых запросов! Подождите немного.")
        return

    mentioned = False
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                mentioned = True

    pollinations_token = os.getenv("POLLINATIONS_TOKEN")
    if not pollinations_token:
        logger.error("POLLINATIONS_TOKEN не установлен!")
        await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
        return

    context_manager.set_generating(chat_id, True)
    typing_task = asyncio.create_task(show_typing(context, chat_id))

    status_message = await message.reply_text("🔊 Обрабатываю аудио...")
    
    # Проверяем размер голосового сообщения
    if message.voice.file_size and message.voice.file_size > 50 * 1024 * 1024:  # 50 МБ
        await status_message.edit_text("❌ Голосовое сообщение слишком большое. Максимум 50 МБ.")
        return
        
    voice_file = await message.voice.get_file()

    temp_dir = tempfile.mkdtemp()
    # Используем уникальные имена файлов с помощью uuid
    unique_id = str(uuid.uuid4())[:8]
    ogg_path = os.path.join(temp_dir, f"voice_{user_id}_{unique_id}.ogg")
    wav_path = os.path.join(temp_dir, f"voice_{user_id}_{unique_id}.wav")

    try:
        await voice_file.download_to_drive(ogg_path)
        
        # Проверяем, что файл действительно загрузился
        if not os.path.exists(ogg_path) or os.path.getsize(ogg_path) == 0:
            await status_message.edit_text("❌ Ошибка загрузки аудиофайла")
            return
            
        logger.info(f"OGG аудио сохранено: {ogg_path} ({os.path.getsize(ogg_path)} байт)")

        try:
            subprocess.run(
                [
                    'ffmpeg',
                    '-i', ogg_path,
                    '-ar', '16000',
                    '-ac', '1',
                    '-y',
                    wav_path
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            logger.info(f"Конвертировано в WAV: {wav_path} ({os.path.getsize(wav_path)} байт)")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
            logger.error(f"Ошибка конвертации аудио: {error_msg}")
            await status_message.edit_text("❌ Ошибка обработки аудио. Попробуйте снова.")
            return
        except subprocess.TimeoutExpired:
            logger.error("Таймаут конвертации аудио")
            await status_message.edit_text("❌ Таймаут обработки аудио. Попробуйте короче.")
            return

        if os.path.getsize(wav_path) > 25 * 1024 * 1024:
            logger.warning(f"Слишком большой аудиофайл: {os.path.getsize(wav_path)} байт")
            await status_message.edit_text("❌ Аудио слишком большое. Максимум 25 МБ.")
            return

        transcription = await asyncio.to_thread(
            transcribe_audio,
            wav_path,
            pollinations_token
        )

        if not transcription or not transcription.strip():
            await status_message.edit_text("❌ Не удалось распознать речь")
            return

        display_transcription = transcription if len(transcription) <= 100 else transcription[:100] + "..."
        await status_message.edit_text(f"🎤 Распознано: {display_transcription}")

        full_name = user.first_name or (user.username if user.username else str(user.id))
        author = {"id": user.id, "name": full_name, "username": user.username}
        context_manager.add_message(chat_id, "user", transcription, author=author)

        messages = context_manager.build_api_messages(chat_id)
        ai_response = await asyncio.to_thread(
            send_to_pollinations,
            messages=messages,
            token=pollinations_token
        )

        if not ai_response:
            await status_message.edit_text("❌ Не удалось сгенерировать ответ")
            # Сохранили распознанный текст, но не отвечаем
            return

        context_manager.add_message(chat_id, "assistant", ai_response)
        await send_long_message(context, chat_id, ai_response, message.message_id)

    except Exception as e:
        logger.exception("Ошибка обработки голосового сообщения")
        await status_message.edit_text(f"❌ Ошибка: {str(e)[:300]}")
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Удалена временная папка: {temp_dir}")
        except Exception as e:
            logger.error(f"Ошибка удаления временных файлов: {e}")

    # В группах отвечаем только если упомянут или ответ на бота
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and not mentioned:
        return


async def handle_image(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user_id, min_interval=2.0):
        await message.reply_text("⚠️ Слишком много запросов с изображениями! Подождите немного.")
        return

    caption = message.caption if message.caption is not None else ""

    mentioned = False
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        bot_username = context.bot.username.lower()
        if f"@{bot_username}" in caption.lower():
            mentioned = True
            caption = re.sub(f"@{bot_username}", "", caption, flags=re.IGNORECASE).strip()

        if not mentioned and message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                mentioned = True

    pollinations_token = os.getenv("POLLINATIONS_TOKEN")
    if not pollinations_token:
        logger.error("POLLINATIONS_TOKEN не установлен!")
        await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
        return

    context_manager.set_generating(chat_id, True)
    typing_task = asyncio.create_task(show_typing(context, chat_id))

    status_message = await message.reply_text("🖼️ Анализирую изображение...")
    
    # Проверяем размер изображения
    if message.photo[-1].file_size and message.photo[-1].file_size > 20 * 1024 * 1024:  # 20 МБ
        await status_message.edit_text("❌ Изображение слишком большое. Максимум 20 МБ.")
        return
        
    photo_file = await message.photo[-1].get_file()
    
    # Создаем временную директорию для изображения
    temp_dir = tempfile.mkdtemp()
    image_path = os.path.join(temp_dir, f"image_{user_id}_{int(time.time())}.jpg")

    try:
        await photo_file.download_to_drive(image_path)
        
        # Проверяем, что файл действительно загрузился
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            await status_message.edit_text("❌ Ошибка загрузки изображения")
            return
            
        logger.info(f"Изображение сохранено: {image_path} ({os.path.getsize(image_path)} байт)")

        question = caption if caption.strip() else "Что на этом изображении?"
        analysis = await asyncio.to_thread(
            analyze_image,
            image_path,
            pollinations_token,
            question
        )

        if not analysis:
            await status_message.edit_text("❌ Не удалось проанализировать изображение")
            return

        full_name = user.first_name or (user.username if user.username else str(user.id))
        author = {"id": user.id, "name": full_name, "username": user.username}
        context_manager.add_message(chat_id, "user", f"Изображение: {question}", author=author)
        context_manager.add_message(chat_id, "assistant", analysis)

        await status_message.edit_text("✅ Анализ завершен!")
        await send_long_message(context, chat_id, analysis, message.message_id)

    except Exception as e:
        logger.exception("Ошибка обработки изображения")
        await status_message.edit_text(f"❌ Ошибка: {str(e)[:300]}")
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Удалена временная папка: {temp_dir}")
        except Exception as e:
            logger.error(f"Ошибка удаления временных файлов: {e}")

    # В группах отвечаем только если упомянут или ответ на бота
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and not mentioned:
        return


async def prompt_command(update: Update, context: CallbackContext):
    """Показывает текущий системный промпт"""
    current_prompt = context_manager.get_system_prompt()
    await update.message.reply_text(
        f"🤖 **Текущий системный промпт:**\n\n{current_prompt}\n\n"
        "Используйте /setprompt для изменения или /resetprompt для сброса.",
        parse_mode=ParseMode.MARKDOWN
    )


async def setprompt_command(update: Update, context: CallbackContext):
    """Устанавливает новый системный промпт"""
    if not context.args:
        await update.message.reply_text(
            "📝 **Использование:**\n"
            "/setprompt <новый промпт>\n\n"
            "**Пример:**\n"
            "/setprompt Ты - эксперт по программированию. Отвечай кратко и по делу."
        )
        return
    
    new_prompt = " ".join(context.args)
    context_manager.set_system_prompt(new_prompt)
    
    await update.message.reply_text(
        f"✅ **Системный промпт обновлен!**\n\n"
        f"Новый промпт:\n{new_prompt}\n\n"
        "Теперь бот будет работать согласно новым инструкциям."
    )


async def resetprompt_command(update: Update, context: CallbackContext):
    """Сбрасывает системный промпт к значению по умолчанию"""
    context_manager.reset_system_prompt()
    default_prompt = context_manager.get_system_prompt()
    
    await update.message.reply_text(
        f"🔄 **Системный промпт сброшен к значению по умолчанию!**\n\n"
        f"Текущий промпт:\n{default_prompt}"
    )


async def update_commands_command(update: Update, context: CallbackContext):
    """Обновляет меню команд бота"""
    try:
        from telegram import BotCommand
        
        commands = [
            BotCommand("start", "🚀 Начать диалог с ботом"),
            BotCommand("help", "❓ Показать справку по командам"),
            BotCommand("reset", "🔄 Очистить историю диалога"),
            BotCommand("prompt", "🎭 Показать текущий системный промпт"),
            BotCommand("setprompt", "✏️ Изменить системный промпт"),
            BotCommand("resetprompt", "🔄 Сбросить промпт к значению по умолчанию"),
        ]
        
        await context.bot.set_my_commands(commands)
        await update.message.reply_text(
            "✅ **Меню команд обновлено!**\n\n"
            "Теперь в чате будут видны подсказки к командам.\n"
            "Нажмите на кнопку меню (/) в поле ввода сообщения."
        )
        logger.info(f"Меню команд обновлено пользователем {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка обновления меню команд: {e}")
        await update.message.reply_text(
            "❌ **Ошибка обновления меню команд!**\n\n"
            f"Детали: {str(e)}"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=True)
    if update and hasattr(update, 'message'):
        try:
            await update.message.reply_text("⚠️ Произошла внутренняя ошибка. Пожалуйста, попробуйте снова.")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e}")


