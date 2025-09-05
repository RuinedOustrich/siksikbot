import os
import logging
import time
import asyncio
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Dict, List, Any, Optional, Tuple
from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackContext

from config.settings import settings

from services.context_manager import context_manager
from services.pollinations_service import (
    send_to_pollinations_async,
    transcribe_audio_async,
    analyze_image_async,
    _is_fallback_message,
)
from utils.telegram_utils import show_typing, strip_advertisement, safe_format_for_telegram, send_long_message
from utils.decorators import handle_errors, track_performance

logger = logging.getLogger(__name__)

# Простая очередь на чат: [{user_message, author, reply_to_message_id}]
PENDING_QUEUES: Dict[int, List[Dict[str, Any]]] = {}

# Защита от дублирования обработки сообщений
PROCESSED_MESSAGES: Dict[int, set] = {}  # chat_id -> set of message_ids


def _validate_user_message(message: str) -> bool:
    """Валидирует сообщение пользователя"""
    if not message or not message.strip():
        return False
    
    # Проверка длины - убираем ограничение, так как Telegram сам ограничивает длину сообщений
    # if len(message) > settings.max_message_length:
    #     logger.warning(f"Сообщение слишком длинное: {len(message)} символов")
    #     return False
    
    # Проверка на потенциально опасные конструкции (более мягкая)
    dangerous_patterns = [
        "ignore previous instructions",
        "forget everything",
        "you are now",
        "act as if",
        "pretend to be",
        "roleplay as",
        "system prompt",
        "jailbreak",
        "dan mode",
        "developer mode",
    ]
    
    message_lower = message.lower()
    for pattern in dangerous_patterns:
        if pattern in message_lower:
            logger.warning(f"Обнаружена потенциально опасная конструкция: {pattern}")
            return False
    
    return True


async def process_queue(context: CallbackContext, chat_id: int):
    """Обрабатывает очередь сообщений для чата"""
    while True:
        next_task = _dequeue_text_task(chat_id)
        if not next_task:
            break
        
        try:
            # Устанавливаем флаг генерации для текстовых операций
            context_manager.set_generating(chat_id, True, "text")
            typing_task = asyncio.create_task(show_typing(context, chat_id))

            # Добавляем сообщение пользователя из очереди в контекст
            q_author = next_task["author"]
            q_user_message = next_task["user_message"]
            q_reply_to = next_task.get("reply_to_message_id")

            context_manager.add_message(chat_id, "user", q_user_message, author=q_author)
            messages = context_manager.build_api_messages(chat_id)
            status = await context.bot.send_message(chat_id=chat_id, text="💭 Думаю...", reply_to_message_id=q_reply_to)

            ai_response = await send_to_pollinations_async(
                messages=messages,
                token=settings.pollinations_token
            )
            if ai_response:
                ai_response_clean = strip_advertisement(ai_response)
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=status.message_id)
                except Exception:
                    pass
                if len(ai_response_clean) > 4000:
                    await send_long_message(context, chat_id, ai_response_clean, q_reply_to)
                else:
                    formatted = safe_format_for_telegram(ai_response_clean)
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=formatted,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_to_message_id=q_reply_to
                        )
                    except Exception as e:
                        logger.debug(f"Markdown send failed in queue: {e}")
                        # Fallback на обычный текст
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=ai_response_clean,
                            reply_to_message_id=q_reply_to
                        )
                context_manager.add_message(chat_id, "assistant", ai_response_clean)
                for mid in context_manager.consume_cleanup_messages(chat_id):
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                    except Exception:
                        pass
            else:
                await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить ответ от API", reply_to_message_id=q_reply_to)
        except Exception:
            logger.exception("Ошибка обработки отложенного запроса")
            # При ошибке очищаем список сообщений для удаления
            context_manager.clear_cleanup_messages(chat_id)
        finally:
            if typing_task:
                typing_task.cancel()
            context_manager.set_generating(chat_id, False, "text")


def _enqueue_text_task(chat_id: int, user_message: str, author: Dict[str, Any], reply_to_message_id: Optional[int]) -> int:
    q = PENDING_QUEUES.get(chat_id)
    if q is None:
        q = []
        PENDING_QUEUES[chat_id] = q
    q.append({
        "type": "text",
        "user_message": user_message,
        "author": author,
        "reply_to_message_id": reply_to_message_id,
    })
    return len(q)


def _dequeue_text_task(chat_id: int) -> Optional[Dict[str, Any]]:
    q = PENDING_QUEUES.get(chat_id) or []
    if not q:
        return None
    task = q.pop(0)
    return task


# --------------- Умное разбиение и псевдостриминг ---------------

def _segment_by_code_blocks(text: str) -> List[Tuple[str, str]]:
    """Разбивает текст на сегменты по блокам кода"""
    segments = []
    current_pos = 0
    
    # Ищем блоки кода
    code_pattern = r'```(\w+)?\n(.*?)\n```'
    for match in re.finditer(code_pattern, text, re.DOTALL):
        start, end = match.span()
        
        # Добавляем текст до блока кода
        if start > current_pos:
            segments.append(("text", text[current_pos:start]))
        
        # Добавляем блок кода
        segments.append(("code", match.group(0)))
        current_pos = end
    
    # Добавляем оставшийся текст
    if current_pos < len(text):
        segments.append(("text", text[current_pos:]))
    
    return segments


def _split_text_by_length(text: str, max_length: int) -> List[str]:
    """Разбивает текст на части по длине, стараясь не разрывать слова"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_pos = 0
    
    while current_pos < len(text):
        end_pos = min(current_pos + max_length, len(text))
        
        # Если это не последняя часть, ищем место для разрыва
        if end_pos < len(text):
            # Ищем последний пробел или перенос строки
            break_pos = text.rfind(' ', current_pos, end_pos)
            if break_pos == -1:
                break_pos = text.rfind('\n', current_pos, end_pos)
            if break_pos == -1:
                break_pos = end_pos
        else:
            break_pos = end_pos
        
        parts.append(text[current_pos:break_pos])
        current_pos = break_pos + 1
    
    return parts


def smart_split_telegram(text: str, max_length: int = 4000) -> List[str]:
    """Умно разбивает текст для Telegram"""
    segments = _segment_by_code_blocks(text)
    parts = []
    current_part = ""
    
    for segment_type, segment_text in segments:
        if segment_type == "code":
            # Блоки кода не разбиваем
            if len(current_part) + len(segment_text) > max_length:
                if current_part:
                    parts.append(current_part.strip())
                    current_part = ""
            current_part += segment_text
        else:
            # Обычный текст разбиваем по длине
            text_parts = _split_text_by_length(segment_text, max_length - len(current_part))
            for i, text_part in enumerate(text_parts):
                if i == 0:
                    current_part += text_part
                else:
                    if current_part:
                        parts.append(current_part.strip())
                    current_part = text_part
                
                if len(current_part) >= max_length:
                    parts.append(current_part.strip())
                    current_part = ""
    
    if current_part:
        parts.append(current_part.strip())
    
    return parts


def add_part_markers(parts: List[str]) -> List[str]:
    """Добавляет маркеры частей к сообщениям"""
    if len(parts) <= 1:
        return parts
    
    marked_parts = []
    for i, part in enumerate(parts):
        marker = f"📄 Часть {i + 1}/{len(parts)}\n\n"
        marked_parts.append(marker + part)
    
    return marked_parts


# --------------- Обработчики сообщений ---------------

@handle_errors
@track_performance
async def handle_message(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем, не обрабатывали ли мы уже это сообщение
    if chat_id in PROCESSED_MESSAGES and message.message_id in PROCESSED_MESSAGES[chat_id]:
        logger.info(f"Сообщение {message.message_id} уже обработано, пропускаем")
        return
    
    # Добавляем сообщение в список обработанных
    if chat_id not in PROCESSED_MESSAGES:
        PROCESSED_MESSAGES[chat_id] = set()
    PROCESSED_MESSAGES[chat_id].add(message.message_id)
    
    # Очищаем старые записи (оставляем только последние 1000)
    if len(PROCESSED_MESSAGES[chat_id]) > 1000:
        old_messages = list(PROCESSED_MESSAGES[chat_id])[:-1000]
        for old_msg_id in old_messages:
            PROCESSED_MESSAGES[chat_id].discard(old_msg_id)
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, chat_id, min_interval=2.0):
        logger.info(f"Rate limit заблокирован для пользователя {user.id} в чате {chat_id}")
        if context_manager.is_generating(chat_id, "text"):
            warn = await message.reply_text("⏳ Подождите, я ещё отвечаю на предыдущий запрос…")
            context_manager.add_cleanup_message(chat_id, warn.message_id)
        else:
            warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
            context_manager.add_cleanup_message(chat_id, warn.message_id)
        return
    
    # Записываем запрос для rate limiting
    from utils.rate_limiter import rate_limiter
    rate_limiter.record_request(user.id, chat_id)

    # Если уже генерируем текстовый ответ для этого чата — ставим запрос в очередь
    if context_manager.is_generating(chat_id, "text"):
        pos = _enqueue_text_task(chat_id, message.text or message.caption or "", {
            "id": user.id,
            "name": user.first_name or (user.username if user.username else str(user.id)),
            "username": user.username,
        }, message.message_id)
        warn = await message.reply_text(f"📚 Запросы поставлены в очередь (вы #{pos})")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    user_message = message.text or message.caption or ""
    
    # Проверяем, ожидает ли пользователь ввода для многошагового процесса
    imagine_state = context_manager.get_user_state(chat_id, "imagine")
    if imagine_state and imagine_state.get("step") == "waiting_description":
        # Проверяем, не прошло ли слишком много времени (5 минут)
        timestamp = imagine_state.get("timestamp", 0)
        if time.time() - timestamp > 300:  # 5 минут
            logger.info(f"Состояние imagine истекло для чата {chat_id}, очищаем")
            context_manager.clear_user_state(chat_id, "imagine")
        else:
            await _handle_imagine_description(update, context, imagine_state, user_message)
            return
    
    # Валидация сообщения
    if not _validate_user_message(user_message):
        err_msg = await message.reply_text("❌ Сообщение содержит недопустимый контент или потенциально опасные конструкции")
        context_manager.add_cleanup_message(chat_id, err_msg.message_id)
        return


    mentioned = False
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        bot_username = context.bot.username.lower()
        settings_s = context_manager.get_settings(chat_id)
        group_mode = settings_s.get("group_mode", "mention_or_reply")

        # Проверяем упоминание бота
        if bot_username and f"@{bot_username}" in user_message.lower():
            mentioned = True

        # Проверяем ответ на сообщение бота
        replied = False
        if message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                replied = True

        if group_mode == "mention_or_reply":
            if not (mentioned or replied):
                logger.info(f"Группа {chat_id}: режим mention_or_reply — игнор без упоминания/ответа")
                return
        elif group_mode == "always":
            pass
        else:
            if group_mode == "mention_only":
                if not mentioned:
                    logger.info(f"Группа {chat_id}: режим mention_only — игнор без упоминания")
                    return
            elif group_mode == "reply_only":
                if not replied:
                    logger.info(f"Группа {chat_id}: режим reply_only — игнор без ответа на бота")
                    return
            elif group_mode == "silent":
                logger.info(f"Группа {chat_id}: режим silent — игнор всего, кроме /команд")
                return

    full_name = user.first_name or (user.username if user.username else str(user.id))
    author = {"id": user.id, "name": full_name, "username": user.username}
    context_manager.add_message(chat_id, "user", user_message, author=author)

    pollinations_token = settings.pollinations_token
    if not pollinations_token:
        logger.error("POLLINATIONS_TOKEN не установлен!")
        await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
        return

    context_manager.set_generating(chat_id, True, "text")
    typing_task = asyncio.create_task(show_typing(context, chat_id))

    try:
        messages = context_manager.build_api_messages(chat_id)
        status_message = await message.reply_text("💭 Думаю...")

        ai_response = await send_to_pollinations_async(
            messages=messages,
            token=pollinations_token
        )

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
            formatted = safe_format_for_telegram(ai_response_clean)
            if len(formatted) > 4000:
                # Разбиваем на части и отправляем с маркерами
                parts = smart_split_telegram(formatted, 4000)
                parts = add_part_markers(parts)
                for i, part in enumerate(parts):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_to_message_id=message.message_id if i == 0 else None,
                        )
                    except Exception as e:
                        logger.debug(f"Markdown send failed for part {i+1}/{len(parts)}: {e}")
                        # Fallback на обычный текст
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            reply_to_message_id=message.message_id if i == 0 else None,
                        )
            else:
                try:
                    await message.reply_text(
                        formatted,
                        reply_to_message_id=message.message_id,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.debug(f"Markdown send failed: {e}")
                    # Fallback на обычный текст
                    await message.reply_text(
                        ai_response_clean,
                        reply_to_message_id=message.message_id
                    )

            context_manager.add_message(chat_id, "assistant", ai_response_clean)
            # Удаляем накопленные предупреждения/ошибки после успешного ответа
            for mid in context_manager.consume_cleanup_messages(chat_id):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        else:
            err_msg = await message.reply_text("❌ Не удалось получить ответ от API")
            context_manager.add_cleanup_message(chat_id, err_msg.message_id)

    except Exception as e:
        logger.exception("Ошибка в handle_message")
        err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
        context_manager.add_cleanup_message(chat_id, err.message_id)
        # При ошибке очищаем список сообщений для удаления
        context_manager.clear_cleanup_messages(chat_id)
    finally:
        if typing_task:
            typing_task.cancel()
        context_manager.set_generating(chat_id, False, "text")

        # Обработаем очередь (если есть) в отдельной задаче
        if PENDING_QUEUES.get(chat_id):
            task = asyncio.create_task(process_queue(context, chat_id))
            # Добавляем обработчик ошибок для задачи очереди
            task.add_done_callback(lambda t: logger.error(f"Ошибка в задаче очереди: {t.exception()}") if t.exception() else None)


@handle_errors
@track_performance
async def handle_voice(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, chat_id, min_interval=2.0):
        warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return
    
    # Записываем запрос для rate limiting
    from utils.rate_limiter import rate_limiter
    rate_limiter.record_request(user.id, chat_id)

    # Если уже генерируем ответ для этого чата — вежливо сообщим и выйдем
    if context_manager.is_generating(chat_id, "voice"):
        warn = await message.reply_text("⏳ Подождите, я ещё обрабатываю предыдущее голосовое сообщение…")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    voice = message.voice
    if not voice:
        err_msg = await message.reply_text("❌ Не удалось получить голосовое сообщение")
        context_manager.add_cleanup_message(chat_id, err_msg.message_id)
        return

    # Групповой режим для голосовых
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        settings_s = context_manager.get_settings(chat_id)
        group_mode = settings_s.get("group_mode", "mention_or_reply")

        # Голосовые обычно без текста, поэтому упоминание недоступно
        mentioned = False
        replied = False
        if message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                replied = True

        if group_mode == "mention_or_reply":
            if not (mentioned or replied):
                logger.info(f"Группа {chat_id}: режим mention_or_reply — игнор голосового без ответа")
                return
        elif group_mode == "always":
            pass
        else:
            if group_mode == "mention_only":
                if not mentioned:
                    logger.info(f"Группа {chat_id}: режим mention_only — голосовое проигнорировано (нет упоминания)")
                    return
            elif group_mode == "reply_only":
                if not replied:
                    logger.info(f"Группа {chat_id}: режим reply_only — голосовое проигнорировано (нет ответа на бота)")
                    return
            elif group_mode == "silent":
                logger.info(f"Группа {chat_id}: режим silent — игнор всего, кроме /команд")
                return

    # Проверяем размер файла
    file_size_mb = voice.file_size / (1024 * 1024) if voice.file_size else 0
    if file_size_mb > settings.max_voice_size_mb:
        err_msg = await message.reply_text(f"❌ Файл слишком большой! Максимальный размер: {settings.max_voice_size_mb}MB")
        context_manager.add_cleanup_message(chat_id, err_msg.message_id)
        return

    context_manager.set_generating(chat_id, True, "voice")
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
            # Используем асинхронный subprocess вместо блокирующего subprocess.run()
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', ogg_path, '-acodec', 'pcm_s16le', 
                '-ar', '16000', '-ac', '1', wav_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Ошибка конвертации аудио: {stderr.decode()}")
                err_msg = await message.reply_text("❌ Ошибка обработки аудио файла")
                context_manager.add_cleanup_message(chat_id, err_msg.message_id)
                return
        except FileNotFoundError:
            err_msg = await message.reply_text("❌ FFmpeg не установлен! Установите ffmpeg для обработки голосовых сообщений.")
            context_manager.add_cleanup_message(chat_id, err_msg.message_id)
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

        transcription = await transcribe_audio_async(
            audio_path=wav_path,
            token=pollinations_token
        )

        if not transcription:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text="❌ Не удалось распознать голосовое сообщение"
            )
            # Добавляем сообщение об ошибке в список для удаления при следующем успешном ответе
            context_manager.add_cleanup_message(chat_id, status_message.message_id)
            return

        # Очищаем временные файлы
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Не удалось удалить временные файлы: {e}")

        
        # Добавляем транскрипцию в контекст
        full_name = user.first_name or (user.username if user.username else str(user.id))
        author = {"id": user.id, "name": full_name, "username": user.username}
        
        # Логируем транскрипцию для отладки
        logger.info(f"Транскрипция голосового сообщения: '{transcription}'")
        
        # Проверяем, является ли транскрипция fallback сообщением
        if _is_fallback_message(transcription):
            # Если это fallback сообщение, отправляем его напрямую в Telegram
            logger.info("Обнаружено fallback сообщение транскрипции, отправляем напрямую в Telegram")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=transcription
            )
            # Удаляем накопленные предупреждения/ошибки после fallback ответа
            for mid in context_manager.consume_cleanup_messages(chat_id):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
            return
        
        # Если это нормальная транскрипция, добавляем в контекст и генерируем ответ
        context_manager.add_message(chat_id, "user", transcription, author=author)

        # Генерируем ответ
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text="💭 Думаю..."
        )

        messages = context_manager.build_api_messages(chat_id)
        start_time = time.time()
        ai_response = await send_to_pollinations_async(
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
            formatted = safe_format_for_telegram(ai_response_clean)
            if len(formatted) > 4000:
                # Для голосовых пока используем старую схему: отправка частями без стриминга
                parts = smart_split_telegram(formatted, 4000)
                parts = add_part_markers(parts)
                for i, part in enumerate(parts):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_to_message_id=message.message_id if i == 0 else None,
                        )
                    except Exception as e:
                        logger.debug(f"Markdown send failed for part {i+1}/{len(parts)}: {e}")
                        # Fallback на обычный текст
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            reply_to_message_id=message.message_id if i == 0 else None,
                        )
            else:
                try:
                    await message.reply_text(
                        formatted,
                        reply_to_message_id=message.message_id,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.debug(f"Markdown send failed: {e}")
                    # Fallback на обычный текст
                    await message.reply_text(
                        ai_response_clean,
                        reply_to_message_id=message.message_id
                    )

            context_manager.add_message(chat_id, "assistant", ai_response_clean)
            # Удаляем накопленные предупреждения/ошибки после успешного ответа
            for mid in context_manager.consume_cleanup_messages(chat_id):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        else:
            err_msg = await message.reply_text("❌ Не удалось получить ответ от API")
            context_manager.add_cleanup_message(chat_id, err_msg.message_id)

    except Exception as e:
        logger.exception("Ошибка в handle_voice")
        if status_message:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ Ошибка: {str(e)[:1000]}"
                )
                # Добавляем отредактированное сообщение об ошибке в список для удаления
                context_manager.add_cleanup_message(chat_id, status_message.message_id)
            except Exception:
                err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                context_manager.add_cleanup_message(chat_id, err.message_id)
        else:
            err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
            context_manager.add_cleanup_message(chat_id, err.message_id)
        # При ошибке очищаем список сообщений для удаления
        context_manager.clear_cleanup_messages(chat_id)
    finally:
        if typing_task:
            typing_task.cancel()
        context_manager.set_generating(chat_id, False, "voice")


@handle_errors
@track_performance
async def handle_image(update: Update, context: CallbackContext):
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Проверяем rate limiting
    if not context_manager.check_rate_limit(user.id, chat_id, min_interval=2.0):
        logger.info(f"Rate limit заблокирован для пользователя {user.id} в чате {chat_id} (изображение)")
        warn = await message.reply_text("⚠️ Слишком много запросов! Подождите немного.")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return
    
    # Записываем запрос для rate limiting
    from utils.rate_limiter import rate_limiter
    rate_limiter.record_request(user.id, chat_id)

    # Если уже генерируем ответ для этого чата — вежливо сообщим и выйдем
    if context_manager.is_generating(chat_id, "image"):
        warn = await message.reply_text("⏳ Подождите, я ещё анализирую предыдущее изображение…")
        context_manager.add_cleanup_message(chat_id, warn.message_id)
        return

    # Получаем изображение
    photo = message.photo[-1] if message.photo else None
    if not photo:
        err_msg = await message.reply_text("❌ Не удалось получить изображение")
        context_manager.add_cleanup_message(chat_id, err_msg.message_id)
        return

    # Проверяем размер файла
    file_size_mb = photo.file_size / (1024 * 1024) if photo.file_size else 0
    if file_size_mb > settings.max_image_size_mb:
        err_msg = await message.reply_text(f"❌ Файл слишком большой! Максимальный размер: {settings.max_image_size_mb}MB")
        context_manager.add_cleanup_message(chat_id, err_msg.message_id)
        return

    # Проверяем групповой режим для изображений
    should_analyze = True
    if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        settings_s = context_manager.get_settings(chat_id)
        group_mode = settings_s.get("group_mode", "mention_or_reply")

        # Проверяем упоминание бота в подписи к изображению
        caption = message.caption or ""
        mentioned = False
        if context.bot.username:
            bot_username = context.bot.username.lower()
            if f"@{bot_username}" in caption.lower():
                mentioned = True

        # Проверяем ответ на сообщение бота
        replied = False
        if message.reply_to_message:
            replied_user = message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                replied = True

        if group_mode == "mention_or_reply":
            if not (mentioned or replied):
                should_analyze = False
                logger.info(f"Группа {chat_id}: режим mention_or_reply — изображение добавлено в контекст без анализа")
        elif group_mode == "always":
            pass
        else:
            if group_mode == "mention_only":
                if not mentioned:
                    should_analyze = False
                    logger.info(f"Группа {chat_id}: режим mention_only — изображение добавлено в контекст без анализа")
            elif group_mode == "reply_only":
                if not replied:
                    should_analyze = False
                    logger.info(f"Группа {chat_id}: режим reply_only — изображение добавлено в контекст без анализа")
            elif group_mode == "silent":
                logger.info(f"Группа {chat_id}: режим silent — игнор изображения")
                return

    # Скачиваем файл для анализа или добавления в контекст
    file = await context.bot.get_file(photo.file_id)
    temp_dir = tempfile.mkdtemp()
    image_path = os.path.join(temp_dir, f"image_{uuid.uuid4()}.jpg")
    
    try:
        await file.download_to_drive(image_path)
        
        if should_analyze:
            # Анализируем изображение и показываем результат
            context_manager.set_generating(chat_id, True, "image")
            typing_task = asyncio.create_task(show_typing(context, chat_id))
            status_message = None

            try:
                status_message = await message.reply_text("🖼️ Анализирую изображение...")
                
                pollinations_token = settings.pollinations_token
                if not pollinations_token:
                    logger.error("POLLINATIONS_TOKEN не установлен!")
                    await message.reply_text("Ошибка конфигурации бота. Пожалуйста, сообщите администратору.")
                    return

                analysis = await analyze_image_async(
                    image_path=image_path,
                    token=pollinations_token
                )

                if not analysis:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_message.message_id,
                        text="❌ Не удалось проанализировать изображение"
                    )
                    context_manager.add_cleanup_message(chat_id, status_message.message_id)
                    return

                # Показываем анализ изображения пользователю
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"🖼️ **Анализ изображения:**\n{analysis}\n\n💡 Теперь вы можете задать мне вопрос об этом изображении!"
                )

                # Добавляем информацию об изображении в контекст
                context_manager.add_image_context(chat_id, analysis)
                
                # Удаляем накопленные предупреждения/ошибки после успешного анализа
                for mid in context_manager.consume_cleanup_messages(chat_id):
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                    except Exception:
                        pass

            except Exception as e:
                logger.exception("Ошибка в handle_image при анализе")
                if status_message:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_message.message_id,
                            text=f"❌ Ошибка: {str(e)[:1000]}"
                        )
                        context_manager.add_cleanup_message(chat_id, status_message.message_id)
                    except Exception:
                        err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                        context_manager.add_cleanup_message(chat_id, err.message_id)
                else:
                    err = await message.reply_text(f"❌ Произошла ошибка: {str(e)[:1000]}")
                    context_manager.add_cleanup_message(chat_id, err.message_id)
                context_manager.clear_cleanup_messages(chat_id)
            finally:
                context_manager.set_generating(chat_id, False, "image")
                if typing_task:
                    typing_task.cancel()
        else:
            # Просто добавляем изображение в контекст без анализа
            pollinations_token = settings.pollinations_token
            if not pollinations_token:
                logger.error("POLLINATIONS_TOKEN не установлен!")
                return

            # Анализируем изображение для добавления в контекст (без показа пользователю)
            analysis = await analyze_image_async(
                image_path=image_path,
                token=pollinations_token
            )

            if analysis:
                # Добавляем информацию об изображении в контекст
                context_manager.add_image_context(chat_id, analysis)
                logger.info(f"Изображение добавлено в контекст для чата {chat_id} без показа анализа")
            else:
                logger.warning(f"Не удалось проанализировать изображение для контекста в чате {chat_id}")

    except Exception as e:
        logger.exception("Ошибка в handle_image при скачивании файла")
        err = await message.reply_text(f"❌ Произошла ошибка при обработке изображения: {str(e)[:1000]}")
        context_manager.add_cleanup_message(chat_id, err.message_id)
    finally:
        # Очищаем временные файлы
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Не удалось удалить временные файлы: {e}")


async def _handle_imagine_description(update: Update, context: CallbackContext, imagine_state: dict, user_message: str):
    """Обрабатывает ввод описания изображения пользователем"""
    chat_id = update.effective_chat.id
    description_message_id = update.effective_message.message_id
    
    try:
        # Извлекаем параметры из состояния
        size_key = imagine_state["size_key"]
        width = imagine_state["width"]
        height = imagine_state["height"]
        style_key = imagine_state.get("style_key")
        
        # Валидируем описание
        if not user_message or len(user_message.strip()) < 3:
            await update.message.reply_text("❌ Описание слишком короткое. Попробуйте еще раз:")
            return
        
        # Генерируем изображение, передавая message_id для последующего удаления
        from bot.handlers.commands import _generate_image
        await _generate_image(chat_id, context.bot, user_message.strip(), width, height, style_key=style_key, description_message_id=description_message_id)
        
    except Exception as e:
        logger.exception("_handle_imagine_description error")
        await update.message.reply_text("❌ Ошибка при генерации изображения. Попробуйте еще раз с /imagine")
        context_manager.clear_user_state(chat_id, "imagine")