#!/usr/bin/env python3
"""
Простой скрипт для запуска бота
"""

import sys
import os
import asyncio

# Добавляем src в путь для импортов
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main():
    try:
        from bot.main import run_bot
        
        # Создаем новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем бота
        loop.run_until_complete(run_bot())
        
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        print(f"Ошибка запуска бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
