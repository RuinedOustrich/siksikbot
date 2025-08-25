import os
import logging
import signal
import sys
import subprocess
import asyncio

# Добавляем src в путь для импортов
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config.settings import settings
from services.context_manager import context_manager
from utils.rate_limiter import rate_limiter
# Убираем импорт delete_advertisement - больше не используется

# Импорты обработчиков
from bot.handlers.commands import (
    start, reset_context, help_command, roles_command, setrole_command,
    resetrole_command, prompt_command, setprompt_command, resetprompt_command,
    update_commands_command, contextlimit_command, setcontextlimit_command,
    imagine_command
)
from bot.handlers.messages import handle_message, handle_voice, handle_image
from bot.handlers.callbacks import role_callback, imagine_callback
from bot.handlers.errors import error_handler


# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, settings.log_level.upper()),
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def check_ffmpeg():
    """Проверяет наличие ffmpeg в системе"""
    try:
        subprocess.run(['ffmpeg', '-version'], 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE, 
                      check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


async def set_bot_commands(application):
    """Устанавливает меню команд для бота"""
    commands = [
        BotCommand("start", "🚀 Начать диалог с ботом"),
        BotCommand("help", "❓ Показать справку по командам"),
        BotCommand("reset", "🔄 Очистить историю диалога"),
        BotCommand("prompt", "🎭 Показать текущий системный промпт"),
        BotCommand("setprompt", "✏️ Изменить системный промпт"),
        BotCommand("resetprompt", "🔄 Сбросить промпт к значению по умолчанию"),
        BotCommand("roles", "🎭 Показать доступные роли"),
        BotCommand("setrole", "🎭 Выбрать роль (философ|психолог|астролог|быдло)"),
        BotCommand("resetrole", "🎭 Сбросить роль к умолчанию"),
        BotCommand("contextlimit", "📏 Показать текущий лимит контекста"),
        BotCommand("setcontextlimit", "✏️ Установить лимит контекста (напр. 30)"),
        BotCommand("imagine", "🖼️ Сгенерировать изображение по описанию")
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Меню команд бота установлено")
    except Exception as e:
        logger.error(f"Ошибка установки меню команд: {e}")

async def main():
    """Основная функция запуска бота"""
    try:
        # Проверяем наличие ffmpeg
        if not check_ffmpeg():
            logger.error("FFmpeg не найден! Установите ffmpeg для обработки голосовых сообщений.")
            logger.warning("Бот запустится без поддержки голосовых сообщений")

        # Создаем приложение с настройками из конфигурации
        application = Application.builder().token(settings.telegram_bot_token).build()
        
        # Настраиваем таймауты
        application.bot.request.timeout = settings.api_timeout
        application.bot.request.connect_timeout = settings.api_timeout // 2
        application.bot.request.read_timeout = settings.api_timeout
        
        logger.info("Бот инициализирован успешно")
        
        return application
        
    except Exception as e:
        logger.error(f"Ошибка инициализации бота: {e}")
        raise


def setup_handlers(application):
    """Настраивает обработчики команд и сообщений"""
    
    logger.info("Настройка обработчиков...")
    
    # Команды бота - работают везде (личные чаты и группы)
    application.add_handler(CommandHandler("start", start), group=0)
    application.add_handler(CommandHandler("reset", reset_context), group=0)
    application.add_handler(CommandHandler("help", help_command), group=0)
    application.add_handler(CommandHandler("prompt", prompt_command), group=0)
    application.add_handler(CommandHandler("setprompt", setprompt_command), group=0)
    application.add_handler(CommandHandler("resetprompt", resetprompt_command), group=0)
    application.add_handler(CommandHandler("roles", roles_command), group=0)
    application.add_handler(CommandHandler("setrole", setrole_command), group=0)
    application.add_handler(CommandHandler("resetrole", resetrole_command), group=0)
    application.add_handler(CommandHandler("contextlimit", contextlimit_command), group=0)
    application.add_handler(CommandHandler("setcontextlimit", setcontextlimit_command), group=0)
    application.add_handler(CommandHandler("updatecmds", update_commands_command), group=0)
    application.add_handler(CommandHandler("imagine", imagine_command), group=0)
    application.add_handler(CallbackQueryHandler(role_callback, pattern=r"^role::"), group=0)
    application.add_handler(CallbackQueryHandler(imagine_callback, pattern=r"^imagine::"), group=0)

    # Убираем глобальную проверку рекламы - теперь она только в ответах AI

    # Обработчики сообщений - более низкий приоритет
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=2)
    application.add_handler(MessageHandler(filters.VOICE, handle_voice), group=2)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image), group=2)

    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    logger.info("Обработчики настроены успешно")


async def run_bot():
    """Запускает бота"""
    application = await main()
    setup_handlers(application)
    
    # Временно отключаем rate limiter cleanup task для отладки
    # rate_limiter.start_cleanup_task()
    
    logger.info("Запуск бота...")
    
    # Запускаем polling (он сам вызывает initialize и start)
    logger.info("Начинаем polling...")
    
    # Инициализируем и запускаем приложение
    await application.initialize()
    await application.start()
    
    # Запускаем polling
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    
    # Ждем остановки
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    
    # Останавливаем приложение
    await application.stop()
    await application.shutdown()


def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    logger.info(f"Получен сигнал {signum}")
    logger.info("Получен сигнал остановки: %s", frame)
    # Не используем sys.exit() здесь, так как это может прервать asyncio


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        sys.exit(1)
