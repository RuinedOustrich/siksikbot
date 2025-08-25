# 🤖 Telegram Bot - СикСик

Интеллектуальный Telegram бот с поддержкой AI-ассистента, обработки голосовых сообщений, анализа изображений и генерации изображений.

## ✨ Возможности

- 💬 **AI-чат** с поддержкой контекста и ролей
- 🎤 **Голосовые сообщения** - автоматическая транскрипция
- 🖼️ **Анализ изображений** - описание и анализ загруженных фото
- 🎨 **Генерация изображений** - создание изображений по описанию
- 👥 **Поддержка групп** - работа в личных чатах и группах
- 🎭 **Роли и персонажи** - философ, психолог, астролог, быдло
- 🔧 **Гибкая настройка** - кастомизация промптов и лимитов
- 🚫 **Антиспам** - автоматическое удаление рекламы
- 📊 **Статистика** - мониторинг использования

## 🚀 Быстрый старт

### Требования

- Python 3.12+
- FFmpeg (для обработки голосовых сообщений)
- Telegram Bot Token
- Pollinations.AI API Token

### Установка

1. **Клонируйте репозиторий:**
```bash
git clone <repository-url>
cd deepseek-telegram-bot
```

2. **Создайте виртуальное окружение:**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

4. **Установите FFmpeg:**
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Скачайте с https://ffmpeg.org/download.html
```

5. **Настройте переменные окружения:**
```bash
cp .env.example .env
# Отредактируйте .env файл
```

### Конфигурация

Создайте файл `.env` со следующими переменными:

```env
# Telegram Bot Token (получите у @BotFather)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Pollinations.AI API Token
POLLINATIONS_TOKEN=your_pollinations_token

# Настройки (опционально)
CONTEXT_LIMIT=20
LOG_LEVEL=INFO
```

### Запуск

```bash
# Активируйте виртуальное окружение
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Запустите бота
python run.py
```

## 🐳 Docker

### Сборка образа

```bash
docker build -t telegram-bot .
```

### Запуск контейнера

```bash
docker run -d \
  --name telegram-bot \
  --env-file .env \
  telegram-bot
```

### Docker Compose

```yaml
version: '3.8'
services:
  bot:
    build: .
    container_name: telegram-bot
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./logs:/app/logs
```

## 📋 Команды бота

### Основные команды

- `/start` - Начать диалог с ботом
- `/help` - Показать справку по командам
- `/reset` - Очистить историю диалога

### Настройка промптов

- `/prompt` - Показать текущий системный промпт
- `/setprompt <текст>` - Изменить системный промпт
- `/resetprompt` - Сбросить промпт к значению по умолчанию

### Роли и персонажи

- `/roles` - Показать доступные роли
- `/setrole <роль>` - Выбрать роль (философ|психолог|астролог|быдло)
- `/resetrole` - Сбросить роль к умолчанию

### Управление контекстом

- `/contextlimit` - Показать текущий лимит контекста
- `/setcontextlimit <число>` - Установить лимит контекста

### Генерация изображений

- `/imagine <описание>` - Сгенерировать изображение по описанию

## 🏗️ Архитектура

### Структура проекта

```
deepseek-telegram-bot/
├── run.py                 # Основной файл запуска бота
├── src/                   # Исходный код
│   ├── bot/              # Основная логика бота
│   │   ├── main.py       # Инициализация и запуск
│   │   └── handlers/     # Обработчики команд и сообщений
│   │       ├── commands.py
│   │       ├── messages.py
│   │       ├── callbacks.py
│   │       └── errors.py
│   ├── config/           # Конфигурация
│   │   └── settings.py   # Настройки с валидацией
│   ├── services/         # Сервисы
│   │   ├── context_manager.py
│   │   └── pollinations_service.py
│   └── utils/            # Утилиты
│       ├── error_handler.py
│       ├── rate_limiter.py
│       └── telegram_utils.py
├── docker/               # Docker конфигурация
│   ├── Dockerfile
│   └── docker-compose.yml
├── logs/                 # Логи бота
├── requirements.txt      # Python зависимости
├── .env.example         # Пример конфигурации
└── README.md            # Документация
```

### Ключевые компоненты

1. **ContextManager** - управляет историей диалогов и настройками
2. **RateLimiter** - контролирует частоту запросов
3. **ErrorHandler** - централизованная обработка ошибок
4. **PollinationsService** - интеграция с AI API

## 🔧 Настройка и кастомизация

### Добавление новых ролей

Отредактируйте `context_manager.py`:

```python
self.predefined_roles = {
    "новая_роль": "Описание новой роли и её поведения",
    # ... существующие роли
}
```

### Изменение лимитов

В файле `.env`:

```env
CONTEXT_LIMIT=30
MAX_VOICE_SIZE_MB=100
MAX_IMAGE_SIZE_MB=20
```

### Настройка логирования

```env
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

## 📊 Мониторинг и логи

### Логи

Логи сохраняются в директории `logs/`:

- `bot.log` - основные логи бота
- Автоматическая ротация логов

### Статистика

Бот собирает статистику использования:

- Количество сообщений
- Используемые роли
- Время активности
- Размер контекста

## 🔒 Безопасность

### Rate Limiting

- Ограничение частоты запросов по пользователям
- Отдельные лимиты для групп
- Sliding window алгоритм

### Валидация

- Проверка токенов при запуске
- Валидация размеров файлов
- Проверка форматов файлов

### Graceful Shutdown

- Корректное завершение работы
- Сохранение состояния
- Очистка ресурсов

## 🐛 Устранение неполадок

### Частые проблемы

1. **FFmpeg не найден**
   ```bash
   sudo apt install ffmpeg  # Ubuntu/Debian
   ```

2. **Ошибка токена**
   - Проверьте правильность TELEGRAM_BOT_TOKEN
   - Убедитесь, что бот не заблокирован

3. **Ошибки API**
   - Проверьте POLLINATIONS_TOKEN
   - Проверьте интернет-соединение

### Логи и отладка

```bash
# Просмотр логов
tail -f logs/bot.log

# Запуск с отладкой
LOG_LEVEL=DEBUG python bot.py
```
