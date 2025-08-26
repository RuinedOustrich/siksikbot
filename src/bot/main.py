import os
import logging
import sys
import subprocess
import asyncio

# Добавляем src в путь для импортов
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config.settings import settings
from services.context_manager import context_manager
from services.pollinations_service import close_http_session
from utils.rate_limiter import rate_limiter
# Убираем импорт delete_advertisement - больше не используется

# Импорты обработчиков
from bot.handlers.commands import (
    start, reset_context, help_command, roles_command,
    prompt_command, setprompt_command, resetprompt_command,
    update_commands_command,
    imagine_command, settings_command, health_command, stop_command
)
from bot.handlers.messages import handle_message, handle_voice, handle_image
from bot.handlers.callbacks import role_callback, imagine_callback, settings_callback, imagine_size_callback, imagine_style_callback, imagine_new_callback, force_stop_callback
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
        BotCommand("settings", "⚙️ Открыть меню настроек"),
        BotCommand("imagine", "🖼️ Сгенерировать изображение по описанию"),
        BotCommand("stop", "🛑 Принудительно остановить все операции"),
        BotCommand("health", "🏥 Показать состояние бота")
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

        # Создаем приложение с настройками из конфигурации и ВКЛЮЧАЕМ ПАРАЛЛЕЛЬНУЮ ОБРАБОТКУ
        application = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).build()
        
        # Настраиваем таймауты и лимиты для параллельных запросов
        application.bot.request.timeout = settings.api_timeout
        application.bot.request.connect_timeout = settings.api_timeout // 2
        application.bot.request.read_timeout = settings.api_timeout
        
        # ВАЖНО: Увеличиваем лимиты для параллельных запросов
        # По умолчанию Telegram Bot API ограничивает количество одновременных запросов
        application.bot.request.connection_pool_size = 100  # Увеличиваем пул соединений
        application.bot.request.connection_pool_maxsize = 100  # Максимальный размер пула
        
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
    application.add_handler(CommandHandler("updatecmds", update_commands_command), group=0)
    application.add_handler(CommandHandler("imagine", imagine_command), group=0)
    application.add_handler(CommandHandler("settings", settings_command), group=0)
    application.add_handler(CommandHandler("health", health_command), group=0)
    application.add_handler(CommandHandler("stop", stop_command), group=0)

    application.add_handler(CallbackQueryHandler(role_callback, pattern=r"^role::"), group=0)
    application.add_handler(CallbackQueryHandler(imagine_callback, pattern=r"^imagine::"), group=0)
    application.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^settings::"), group=0)
    application.add_handler(CallbackQueryHandler(imagine_size_callback, pattern=r"^imagine_size::"), group=0)
    application.add_handler(CallbackQueryHandler(imagine_style_callback, pattern=r"^imagine_style::"), group=0)
    application.add_handler(CallbackQueryHandler(imagine_new_callback, pattern=r"^imagine_new"), group=0)
    application.add_handler(CallbackQueryHandler(force_stop_callback, pattern=r"^force_stop"), group=0)

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
    
    # Запускаем cleanup task для rate limiter
    rate_limiter.start_cleanup_task()
    
    logger.info("Запуск бота...")
    
    # Запускаем polling (он сам вызывает initialize и start)
    logger.info("Начинаем polling...")
    
    # Инициализируем и запускаем приложение
    await application.initialize()
    await application.start()

    # Устанавливаем команды бота
    await set_bot_commands(application)
    
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
    
    # Закрываем HTTP сессию
    await close_http_session()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        sys.exit(1)
