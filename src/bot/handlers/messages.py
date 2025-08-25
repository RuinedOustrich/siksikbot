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

from config.settings import settings

from services.context_manager import context_manager
from services.pollinations_service import (
    send_to_pollinations,
    transcribe_audio,
    analyze_image,
    generate_image,
)
from utils.telegram_utils import show_typing, send_long_message, strip_advertisement

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    logger.info(f"Получено текстовое сообщение от пользователя {user.id} в чате {chat_id}: {message.text[:50]}...")
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, min_interval=1.0):
        warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return
    # Убираем проверку рекламы для входящих сообщений

    # Если уже генерируем ответ для этого чата — вежливо сообщим и выйдем
    if context_manager.is_generating(chat_id):
        warn = await message.reply_text("⏳ Подождите, я ещё отвечаю на предыдущий запрос…")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
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

    pollinations_token = settings.pollinations_token
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
            # Удаляем рекламный блок в конце ответа, если есть
            ai_response_clean = strip_advertisement(ai_response)
            if len(ai_response_clean) > 4000:
                await send_long_message(context, chat_id, ai_response_clean, message.message_id)
            else:
                await message.reply_text(
                    ai_response_clean,
                    reply_to_message_id=message.message_id,
                    parse_mode=ParseMode.MARKDOWN
                )

            context_manager.add_message(chat_id, "assistant", ai_response_clean)
            # Удаляем накопленные предупреждения/ошибки после успешного ответа
            for mid in context_manager.consume_cleanup_messages(chat_id):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
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
                err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                context_manager.add_cleanup_message(chat_id, err.message_id)
        else:
            err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
            context_manager.add_cleanup_message(chat_id, err.message_id)
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()


async def handle_voice(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, min_interval=2.0):
        warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    # Если уже генерируем ответ для этого чата — вежливо сообщим и выйдем
    if context_manager.is_generating(chat_id):
        warn = await message.reply_text("⏳ Подождите, я ещё отвечаю на предыдущий запрос…")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    voice = message.voice
    if not voice:
        await message.reply_text("❌ Не удалось получить голосовое сообщение")
        return

    # Проверяем размер файла
    file_size_mb = voice.file_size / (1024 * 1024) if voice.file_size else 0
    if file_size_mb > 50:  # 50MB лимит
        await message.reply_text("❌ Файл слишком большой! Максимальный размер: 50MB")
        return

    context_manager.set_generating(chat_id, True)
    typing_task = asyncio.create_task(show_typing(context, chat_id))
    status_message = None

    try:
        # Скачиваем файл
        status_message = await message.reply_text("🎵 Обрабатываю голосовое сообщение...")
        
        file = await context.bot.get_file(voice.file_id)
        temp_dir = tempfile.mkdtemp()
        ogg_path = os.path.join(temp_dir, f"voice_{uuid.uuid4()}.ogg")
        
        await file.download_to_drive(ogg_path)
        
        # Конвертируем в WAV
        wav_path = os.path.join(temp_dir, f"voice_{uuid.uuid4()}.wav")
        try:
            subprocess.run([
                'ffmpeg', '-i', ogg_path, '-acodec', 'pcm_s16le', 
                '-ar', '16000', '-ac', '1', wav_path
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка конвертации аудио: {e}")
            await message.reply_text("❌ Ошибка обработки аудио файла")
            return
        except FileNotFoundError:
            await message.reply_text("❌ FFmpeg не установлен! Установите ffmpeg для обработки голосовых сообщений.")
            return

        # Транскрибируем
        pollinations_token = settings.pollinations_token
        if not pollinations_token:
            logger.error("POLLINATIONS_TOKEN не установлен!")
            await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
            return

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text="🎤 Транскрибирую голосовое сообщение..."
        )

        transcription = await asyncio.to_thread(
            transcribe_audio,
            audio_path=wav_path,
            token=pollinations_token
        )

        if not transcription:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text="❌ Не удалось распознать голосовое сообщение"
            )
            return

        # Очищаем временные файлы
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Не удалось удалить временные файлы: {e}")

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text=f"🎤 **Распознанный текст:**\n{transcription}"
        )

        # Добавляем транскрипцию в контекст
        full_name = user.first_name or (user.username if user.username else str(user.id))
        author = {"id": user.id, "name": full_name, "username": user.username}
        context_manager.add_message(chat_id, "user", transcription, author=author)

        # Генерируем ответ
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text="💭 Думаю..."
        )

        messages = context_manager.build_api_messages(chat_id)
        start_time = time.time()
        ai_response = await asyncio.to_thread(
            send_to_pollinations,
            messages=messages,
            token=pollinations_token
        )
        logger.info(f"Ответ на голосовое получен за {time.time() - start_time:.2f} сек")

        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=status_message.message_id
            )
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        if ai_response:
            # Удаляем рекламный блок в конце ответа, если есть
            ai_response_clean = strip_advertisement(ai_response)
            if len(ai_response_clean) > 4000:
                await send_long_message(context, chat_id, ai_response_clean, message.message_id)
            else:
                await message.reply_text(
                    ai_response_clean,
                    reply_to_message_id=message.message_id,
                    parse_mode=ParseMode.MARKDOWN
                )

            context_manager.add_message(chat_id, "assistant", ai_response_clean)
            # Удаляем накопленные предупреждения/ошибки после успешного ответа
            for mid in context_manager.consume_cleanup_messages(chat_id):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        else:
            await message.reply_text("❌ Не удалось получить ответ от API")

    except Exception as e:
        logger.exception("Ошибка в handle_voice")
        if status_message:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ Ошибка: {str(e)[:1000]}"
                )
            except Exception:
                err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                context_manager.add_cleanup_message(chat_id, err.message_id)
        else:
            err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
            context_manager.add_cleanup_message(chat_id, err.message_id)
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()


async def handle_image(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, min_interval=2.0):
        warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    # Если уже генерируем ответ для этого чата — вежливо сообщим и выйдем
    if context_manager.is_generating(chat_id):
        warn = await message.reply_text("⏳ Подождите, я ещё отвечаю на предыдущий запрос…")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    # Получаем изображение
    photo = message.photo[-1] if message.photo else None
    if not photo:
        await message.reply_text("❌ Не удалось получить изображение")
        return

    # Проверяем размер файла
    file_size_mb = photo.file_size / (1024 * 1024) if photo.file_size else 0
    if file_size_mb > 10:  # 10MB лимит
        await message.reply_text("❌ Файл слишком большой! Максимальный размер: 10MB")
        return

    context_manager.set_generating(chat_id, True)
    typing_task = asyncio.create_task(show_typing(context, chat_id))
    status_message = None

    try:
        # Скачиваем файл
        status_message = await message.reply_text("🖼️ Анализирую изображение...")
        
        file = await context.bot.get_file(photo.file_id)
        temp_dir = tempfile.mkdtemp()
        image_path = os.path.join(temp_dir, f"image_{uuid.uuid4()}.jpg")
        
        await file.download_to_drive(image_path)

        # Анализируем изображение
        pollinations_token = settings.pollinations_token
        if not pollinations_token:
            logger.error("POLLINATIONS_TOKEN не установлен!")
            await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
            return

        analysis = await asyncio.to_thread(
            analyze_image,
            image_path=image_path,
            token=pollinations_token
        )

        # Очищаем временные файлы
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Не удалось удалить временные файлы: {e}")

        if not analysis:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text="❌ Не удалось проанализировать изображение"
            )
            return

        # Показываем анализ изображения пользователю
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text=f"🖼️ **Анализ изображения:**\n{analysis}\n\n💡 Теперь вы можете задать мне вопрос об этом изображении!"
        )

        # Добавляем информацию об изображении в контекст как системное сообщение
        context_manager.add_image_context(chat_id, analysis)

    except Exception as e:
        logger.exception("Ошибка в handle_image")
        if status_message:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ Ошибка: {str(e)[:1000]}"
                )
            except Exception:
                err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                context_manager.add_cleanup_message(chat_id, err.message_id)
        else:
            err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
            context_manager.add_cleanup_message(chat_id, err.message_id)
    finally:
        context_manager.set_generating(chat_id, False)
        if typing_task:
            typing_task.cancel()
