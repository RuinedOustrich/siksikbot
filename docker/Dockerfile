# Базовый образ
FROM python:3.12-slim

# Установка зависимостей ОС
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание непривилегированного пользователя
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Рабочая директория
WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .

# Установка Python-зависимостей
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir certifi --force-reinstall

# Копирование исходного кода
COPY . .

# Создание директории для логов
RUN mkdir -p /app/logs && chown -R botuser:botuser /app

# Переключение на непривилегированного пользователя
USER botuser

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Команда запуска
CMD ["python3", "run.py"]