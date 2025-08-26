# ===== BUILD STAGE =====
FROM python:3.12-slim AS builder

# Консервативные настройки Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

# Build dependencies для компиляции psutil и других пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Установка python-зависимостей
COPY ../requirements.txt /requirements.txt
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir --user -r /requirements.txt

# ===== RUNTIME STAGE =====
FROM python:3.12-slim

# Консервативные настройки Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    PATH=/home/botuser/.local/bin:$PATH

# Только runtime зависимости (без build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Копируем установленные Python пакеты из builder stage
COPY --from=builder /root/.local /home/botuser/.local
RUN chown -R botuser:botuser /home/botuser/.local

# Рабочая директория
WORKDIR /app

# Создаем каталог для логов перед копированием
RUN mkdir -p /app/logs

# Копирование исходников (файлы, исключённые .dockerignore, не попадут в образ)
COPY ../ /app

# Устанавливаем права на файлы
RUN chown -R botuser:botuser /app

# Запуск от непривилегированного пользователя
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python3 docker/healthcheck.py || exit 1

# Точка входа
CMD ["python3", "run.py"]
