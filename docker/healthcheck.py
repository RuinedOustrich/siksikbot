#!/usr/bin/env python3
"""
Health check script for Docker container
"""
import sys
import os
import time

def check_bot_health():
    """Проверяет состояние бота"""
    try:
        # Проверяем, что процесс бота запущен
        import psutil
        
        # Ищем процесс Python с run.py
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] == 'python3' and 'run.py' in ' '.join(proc.info['cmdline']):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return False
        
    except ImportError:
        # Если psutil недоступен, проверяем файл логов
        log_file = 'logs/bot.log'
        if os.path.exists(log_file):
            # Проверяем, что лог файл обновлялся недавно (в течение 5 минут)
            mtime = os.path.getmtime(log_file)
            return (time.time() - mtime) < 300
        
        return False

def main():
    """Основная функция health check"""
    if check_bot_health():
        print("Bot is healthy")
        sys.exit(0)
    else:
        print("Bot is not responding")
        sys.exit(1)

if __name__ == "__main__":
    main()
