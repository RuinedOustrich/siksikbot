# 📘 Project Best Practices

## 1. Project Purpose
Интеллектуальный Telegram-бот «СикСик» на Python 3.12, использующий Pollinations.AI для:
- диалогового AI-чата с сохранением контекста
- транскрипции голосовых сообщений (FFmpeg + Pollinations audio)
- анализа изображений (vision)
- генерации изображений по текстовому описанию
Поддерживаются персональные и групповые чаты, роли/персоны, ограничение частоты запросов и централизованное логирование.

## 2. Project Structure
- run.py — точка входа (создает и запускает event loop, вызывает bot.main.run_bot)
- src/
  - bot/
    - main.py — инициализация Application, конфигурация логирования, регистрация хендлеров, запуск polling
    - handlers/
      - commands.py — команды (/start, /help, /reset, /prompt, /setprompt, /resetprompt, /roles, /contextlimit, /setcontextlimit, /updatecmds, /imagine)
      - messages.py — обработчики текстов, голосовых и изображений
      - callbacks.py — обработка callback_data для ролей и перегенерации изображений
      - errors.py — централизованный error handler уровня telegram-бота
  - config/
    - settings.py — Pydantic v2 настройки (env, валидация, дефолты)
  - services/
    - context_manager.py — хранение контекстов, промптов, ролей, лимитов, статистики, флагов «генерации»
    - pollinations_service.py — интеграция с Pollinations API (chat, audio, vision, image)
  - utils/
    - telegram_utils.py — утилиты: «печатает…», разбиение длинных сообщений, удаление рекламных блоков
    - error_handler.py — вспомогательные классы/утилиты для ошибок (непосредственно не подключен как handler)
- docker/
  - Dockerfile, docker-compose.yml — сборка/запуск контейнера (ffmpeg предустановлен)
- tests/ — каталог под тес��ы (на текущий момент пустой)
- requirements.txt — зависимости
- .env.example / .env — конфигурация окружения
- logs/ — файлы логов

Роли ключевых компонентов:
- Settings (config/settings.py): загрузка .env, строгая валидация ключевых параметров, единый источник правды для конфигов
- ContextManager: управление контекстом диалога, ролями/персонами, системным промптом, лимитами, флагами генерации, статистикой
- Handlers: четкое разделение по типам (команды, сообщения, коллбеки, ошибки)
- Services: интеграция с внешними API (Pollinations), кодирование/отправка медиа, сетевые вызовы
- Utils: инфраструктурные утилиты для Telegram и обработки текста

## 3. Test Strategy
Текущее состояние: каталог tests/ присутствует, но тесты отсутствуют. Рекомендуемый подход:
- Фреймворк: pytest + pytest-asyncio
- Структура:
  - tests/unit/test_context_manager.py — п��ведение ContextManager (лимиты, роли, сборка сообщений для API)
  - tests/unit/test_pollinations_service.py — кодирование медиа, формирование payload, разбор ответов, обработка ошибок
  - tests/unit/test_telegram_utils.py — разбиение длинных сообщений, удаление рекламы, show_typing (с таймаутами)
  - tests/integration/test_handlers_messages.py — сценарии: упоминания в группах, генерация ответов, ошибки API (моки)
  - tests/integration/test_handlers_commands.py — смена ролей, лимитов, промптов; imagine параметры
- Мокинг:
  - Мокать HTTP-вызовы (requests) и Pollinations API-обертки
  - Мокать context.bot.* методы (send_message, send_photo, edit_message_text, delete_message)
  - Для FFmpeg — мокать subprocess.run
- Философия тестирования:
  - Юнит-тесты для чистой логики (ContextManager, utils, формирование payload)
  - Интеграционные тесты для хендлеров с фейковыми Update/Context
  - Покрывать ветки ошибок и таймаутов
  - Цель пок��ытия: 70%+ на критических модулях (services, context)

## 4. Code Style
- Язык/Async:
  - python-telegram-bot v20 — использовать async def для хендлеров, не блокировать event loop
  - Для сетевых/CPU-блокирующих операций использовать asyncio.to_thread или внешние процессы (FFmpeg)
- Типизация:
  - Добавлять явные типы в публичные функции и методы, особенно в services и context
- Логирование:
  - Единая конфигурация logging в bot/main.py (StreamHandler + FileHandler logs/bot.log)
  - Логировать ключевые события (старт/стоп, команды, ошибки, таймауты)
- Конфигурация:
  - Все параметры — через Settings (Pydantic v2). Для новых параметров добавлять валидаторы
- Обработка ошибок:
  - try/except вокруг внешних вызовов; возвращать понятные пользователю сообщения
  - В error_handler (bot/handlers/errors.py) отвечать пользователю и добавлять message_id в cleanup для последующего удаления
- Telegram-ограничения:
  - Длина сообщений: использовать utils.send_long_message при > 4000 символов
  - Markdown: по умолчанию ParseMode.MARKDOWN; избегать синтаксиса V2, если не включен
  - callback_data <= 64 байт — держать формат коллбеков компактным (см. imagine::WxH)
- Группы и упоминания:
  - В группах реагировать только при упоминании бота или в ответе на сообщение бота
  - Сообщения сохранять в контекст даже без ответа (для истории)
- Реклама:
  - Использовать utils.strip_advertisement для очистки рекламных блоков из AI-ответов
- Конкурентный доступ:
  - Перед длительными задачами выставлять context_manager.set_generating(chat_id, True), снимать в finally
  - Rate limiting — через context_manager.check_rate_limit(user_id, ...)

## 5. Common Patterns
- Регистрация хендлеров (bot/main.py):
  - Команды и CallbackQueryHandler — group=0 (высокий приоритет)
  - Сообщения — group=2 (ниже приори��ет)
  - error_handler — через application.add_error_handler
- Формат callback_data:
  - role::<key> — выбор роли
  - imagine::WxH — перегенерация изображения указанного размера
- ContextManager:
  - add_message(chat_id, role, content, author)
  - build_api_messages(chat_id) — включает system prompt и автора в user-сообщениях
  - add_image_context(chat_id, analysis) — добавляет системное сообщение с анализом изображения
  - get/set_context_limit, set_role, set/reset_system_prompt, is_generating
- Сетевые вызовы:
  - services.pollinations_service: все HTTP через requests с таймаутами и разбором ошибок
  - Длительные операции — через asyncio.to_thread
- Медиа и файлы:
  - Голос: скачивание -> FFmpeg конверсия в WAV 16kHz mono -> транскрипция
  - Изображения: скачивание -> base64 -> vision API
  - Удалять временные файлы (shutil.rmtree) в finally/try
- Сообщения пользователю:
  - Промежуточные статусы ("Думаю...", "Транскрибирую…", "Анализирую…")
  - По успешном ответе — очищать накопленные предупреждения (consume_cleanup_messages)

## 6. Do's and Don'ts
- ✅ Делать
  - Использовать Settings для всех новых конфигов, добавлять в .env.example
  - Оборачивать внешние вызовы в try/except, логировать и отвечать пользователю
  - Хранить и уважать флаг is_generating, чтобы не перегружать чат
  - Разбивать длинные ответы send_long_message
  - Проверять размеры медиа-файлов против настроек (max_voice_size_mb, max_image_size_mb)
  - Писать асинхронные хендлеры и избегать блокировок event loop
  - Поддерживать русский текст UI и эмодзи-список команд
- ❌ Не делать
  - Не выполнять блокирующие операции в хендлерах без asyncio.to_thread
  - Не превышать лимиты Telegram (длина сообщений, callback_data)
  - Не смешивать бизнес-логику и Telegram-специфику в services — держать адаптеры чистыми
  - Не хардкодить секрет�� — только через .env / Settings

## 7. Tools & Dependencies
- Библиотеки:
  - python-telegram-bot==20.6 — Telegram API (asyncio)
  - requests — HTTP вызовы к Pollinations
  - pydantic v2 + pydantic-settings — конфигурация и валидация
  - python-dotenv — поддержка .env загрузки (через pydantic-settings)
  - aiofiles — зарезервировано/возможное использование для асинхронной работы с файлами
- Системные зависимости:
  - FFmpeg — обязателен для голосовых сообщений (конверсия OGG -> WAV)
- Запуск:
  - Локально: python run.py (при активированном venv и заполненном .env)
  - Docker: docker build -t telegram-bot . && docker run --env-file .env -v ./logs:/app/logs telegram-bot
  - Compose: docker-compose up -d
- Замечание по Docker healthcheck:
  - В Dockerfile/docker-compose задана проверка http://localhost:8080/health, но HTTP-сервис не поднимается ботом. Либо отключите healthcheck, либо реализуйте лёгкий HTTP-эндпоинт (например, через aiohttp) и проброс порта.

## 8. Other Notes
- Для добавления новых команд/ролей:
  - Хендлеры — в bot/handlers; регистрацию — в bot/main.setup_handlers
  - Обновить меню команд через set_bot_commands и /updatecmds
  - Новые роли — добавить текст в ContextManager.predefined_roles
- Формат ответов:
  - По умолчанию ParseMode.MARKDOWN. Избегать спецсимволов Markdown V2; при сомнении экранировать
  - Чистите рекламные вставки из AI-ответов strip_advertisement
- Ограничения генерации изображений:
  - Ширина/высота ограничены 256..1536; seed опционален
  - Держите callback_data коротким (например, imagine::1024x1024)
- Контекст и приватность:
  - Сохраняйте только необходимое; контекст ограничен лимитом (по умолчанию settings.context_limit)
- Расширение конфигурации:
  - Новые поля добавлять в Settings c валидаторами и .env.example; использовать settings �� коде
