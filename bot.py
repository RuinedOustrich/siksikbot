import os
import logging
import subprocess
import asyncio
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from handlers import (
    start,
    reset_context,
    help_command,
    prompt_command,
    setprompt_command,
    resetprompt_command,
    update_commands_command,
    handle_message,
    handle_voice,
    handle_image,
    error_handler,
)
from telegram_utils import delete_advertisement
from telegram import BotCommand


load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
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
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Меню команд бота установлено")
    except Exception as e:
        logger.error(f"Ошибка установки меню команд: {e}")

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        logger.error("FFmpeg не найден! Установите ffmpeg для обработки голосовых сообщений.")
        logger.warning("Бот запустится без поддержки голосовых сообщений")

    # Создаем приложение с увеличенными таймаутами
    application = Application.builder().token(token).build()
    
    # Увеличиваем таймауты для медленного интернета
    application.bot.request.timeout = 60.0
    application.bot.request.connect_timeout = 30.0
    application.bot.request.read_timeout = 60.0

    # Команды бота - работают везде (личные чаты и группы)
    application.add_handler(CommandHandler("start", start), group=0)
    application.add_handler(CommandHandler("reset", reset_context), group=0)
    application.add_handler(CommandHandler("help", help_command), group=0)
    application.add_handler(CommandHandler("prompt", prompt_command), group=0)
    application.add_handler(CommandHandler("setprompt", setprompt_command), group=0)
    application.add_handler(CommandHandler("resetprompt", resetprompt_command), group=0)
    application.add_handler(CommandHandler("updatecmds", update_commands_command), group=0)

    # Обработчик рекламы - самый высокий приоритет
    application.add_handler(
        MessageHandler(filters.TEXT | filters.CAPTION, delete_advertisement),
        group=1
    )

    # Обработчики сообщений - более низкий приоритет
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        group=2
    )

    application.add_handler(
        MessageHandler(filters.VOICE, handle_voice),
        group=2
    )

    application.add_handler(
        MessageHandler(filters.PHOTO, handle_image),
        group=2
    )

    application.add_error_handler(error_handler)

    logger.info("Бот запущен с поддержкой голоса и изображений...")
    
    try:
        # Устанавливаем меню команд для бота
        await set_bot_commands(application)
        
        # Запускаем бота
        logger.info("Запуск бота...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Бот успешно запущен!")
        
        # Ждем обновлений
        try:
            await asyncio.Event().wait()  # Бесконечное ожидание
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            await application.stop()
            await application.shutdown()
            
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        # Fallback - простой запуск
        logger.info("Запуск бота в простом режиме...")
        application.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

 
