## Мониторинг QA-вакансий Avito + уведомления в Telegram

Скрипт `search_qa.py` мониторит страницу вакансий Avito Career (направление разработка, тэг QA), печатает количество и список найденных вакансий и, при необходимости, отправляет сводку в Telegram.

### Возможности
- Получение HTML страницы и парсинг названий вакансий (BeautifulSoup или резервные методы)
- Подсчёт количества вакансий 
- Вывод результатов в консоль
- Отправка уведомления в Telegram (если заданы переменные окружения)

## Требования
- Python 3.9+
- Зависимости из `requirements.txt`:
  - `beautifulsoup4`, `lxml`
  - `python-dotenv` — автозагрузка переменных из файла `.env`
  - `certifi` — актуальный набор корневых сертификатов для HTTPS

## Установка

### Создать и активировать виртуальное окружение (рекомендуется)
```bash
python3 -m venv .venv
source .venv/bin/activate  # для zsh/bash на macOS/Linux
```

### Установить зависимости
```bash
pip install -U pip setuptools wheel
pip install -r requirements.txt
```

## Конфигурация окружения (.env)
Скрипт читает переменные окружения автоматически через `python-dotenv` при наличии файла `.env` в корне проекта.

Создайте файл `.env` со следующими переменными (для Telegram-уведомлений):
```bash
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=ваш_токен
TELEGRAM_CHAT_ID=ваш_chat_id
EOF
```

- **TELEGRAM_BOT_TOKEN**: токен вашего Telegram-бота
- **TELEGRAM_CHAT_ID**: ID чата/канала, куда слать уведомления

Если `.env` отсутствует или переменные пустые — отправка в Telegram будет пропущена, скрипт просто выведет результат в консоль.

## Запуск

### Без отправки в Telegram
```bash
python search_qa.py --no-telegram
```

### С уведомлением в Telegram (если задан `.env`)
```bash
python search_qa.py
```

### Пример вывода в консоль
```
Найдено вакансий: 5
QA Engineer (Mobile)
QA Automation Engineer (Backend)
...
```

## Запуск в Docker

### Сборка образа
```bash
docker build -t avito-qa:latest .
```

### Запуск (локально)
- Без Telegram:
```bash
docker run --rm avito-qa:latest python /app/search_qa.py --no-telegram
```
- С Telegram (используйте файл окружения):
```bash
cat > env.list << 'EOF'
TELEGRAM_BOT_TOKEN=ваш_токен
TELEGRAM_CHAT_ID=ваш_chat_id
EOF
docker run --rm --env-file=env.list avito-qa:latest
```

### Логи
```bash
docker logs -f <container_id>
```

## Деплой на удалённый сервер (SSH)

Вариант A: копирование исходников и сборка на сервере
```bash
ssh user@host 'mkdir -p ~/apps/avito-qa'
rsync -av --delete --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
  --exclude '.DS_Store' --exclude '*.log' --exclude '.env' \
  ./ user@host:~/apps/avito-qa/

ssh user@host 'cd ~/apps/avito-qa && docker build -t avito-qa:latest .'

# создайте файл env.list на сервере с переменными
ssh user@host 'bash -lc "cat > ~/apps/avito-qa/env.list << EOF\nTELEGRAM_BOT_TOKEN=ваш_токен\nTELEGRAM_CHAT_ID=ваш_chat_id\nEOF"'

ssh user@host 'docker run -d --name avito-qa --restart unless-stopped --env-file ~/apps/avito-qa/env.list avito-qa:latest'
```

Вариант B: сборка локально и перенос образа
```bash
# 1) собрать локально
docker build -t avito-qa:latest .
# 2) сохранить в архив
docker save avito-qa:latest | gzip > avito-qa.tar.gz
# 3) передать на сервер
scp avito-qa.tar.gz user@host:~/
# 4) загрузить на сервере и запустить
ssh user@host 'gunzip -c ~/avito-qa.tar.gz | docker load && \
  docker run -d --name avito-qa --restart unless-stopped --env-file ~/env.list avito-qa:latest'
```

### Планирование запуска в контейнере (cron на сервере)
Если требуется запуск по расписанию, используйте `cron` хоста:
```bash
crontab -e
# пример: ежедневный запуск в 10:00
0 10 * * * docker run --rm --env-file /path/to/env.list avito-qa:latest >> /var/log/avito-qa.log 2>&1
```

## Планировщик (cron)
Пример ежедневного запуска в 10:00 с логированием в файл `search_qa.log`:
```bash
0 10 * * * /usr/bin/env zsh -lc 'cd "/absolute/path/to/Avito" && ./.venv/bin/python ./search_qa.py >> ./search_qa.log 2>&1'
```

Замените `/absolute/path/to/Avito` на абсолютный путь к каталогу проекта. Рекомендуется запускать через Python из вашего `.venv`.

## Отладка и частые проблемы

### Ошибка SSL: CERTIFICATE_VERIFY_FAILED
- В проект добавлен `certifi`, и код использует его CA-бандл для HTTPS. После установки зависимостей запустите:
  ```bash
  pip install -r requirements.txt
  ```
- Если ошибка сохраняется на macOS (python.org installer), выполните штатный скрипт установки сертификатов:
  ```bash
  /Applications/Python\ 3.13/Install\ Certificates.command || true
  ```
- Временный обход (не как постоянное решение):
  ```bash
  export SSL_CERT_FILE="$(python3 -c 'import certifi,sys; sys.stdout.write(certifi.where())')"
  ```

### Переменные окружения не подхватываются
- Проверьте, что файл `.env` лежит рядом с `search_qa.py` (в корне проекта)
- Убедитесь, что в `.env` нет лишних кавычек/пробелов и значения непустые
- Можно проверить загрузку так:
  ```bash
  python -c 'import os; print(os.getenv("TELEGRAM_BOT_TOKEN"))'
  ```

## Структура проекта
- `search_qa.py` — основной скрипт
- `requirements.txt` — зависимости проекта
- `README.md` — эта документация
- `.env` — переменные окружения (не коммитить)

