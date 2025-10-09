# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Системные зависимости (для сборки некоторых пакетов, напр. lxml)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libxml2-dev \
       libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Установка зависимостей
COPY requirements.txt ./
RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY search_qa.py ./
COPY .env ./

# По умолчанию запускаем скрипт (переменные окружения передавайте через --env-file или -e)
CMD ["python", "/app/search_qa.py"]


