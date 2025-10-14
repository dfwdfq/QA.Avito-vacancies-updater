## Мониторинг QA-вакансий Avito
Проект состоит из 2 частей:
- Скрипт реализует сбор актуальной информации об открытых вакансиях QA в Avito.
- Бот автоматизирует сбор информации с указанной периодичностью, делая выгрузку в Telegram.


# установка(для GNU/Linux)
```bash
python -m venv venv
source /venv/bin/activate
python -m pip install -r requirements.txt
```

# использование
Активировав виртуальное окружение и установив зависимости из __requirements.txt__.
```bash
chmod +x search_qa.py
./search_qa.py
```

# развертка бота
В корневой директории проекта необходимо создать __.env__:
```bash
TELEGRAM_BOT_TOKEN=ваш_токен
TELEGRAM_CHAT_ID=ваш_chat_id
```

- **TELEGRAM_BOT_TOKEN**: токен вашего Telegram-бота
- **TELEGRAM_CHAT_ID**: ID чата/канала, куда слать уведомления


Если `.env` отсутствует или переменные пустые — отправка в Telegram будет пропущена, скрипт просто выведет результат в STDOUT.

### Примечание
Изначальным хостом для бота подразумевалась и является RaspberryPI, что приводит к ограничением RAM.
Как результат это оказывает ощутимое влияние на ход работы бота, видное при даже беглом взгляде на 
исходники. Отсюда же следует нецелесообразность использования контейнеризации.

### Custom daemon vs Cron vs Docker
В масштабе проекта этого бота Docker -  overkill инструмент. Он слишком большой и его возможности
не пропорциональны простоте приложения. Вместе с тем, RPI имеет заметные ограничения RAM и они ощутимы
при использовании высокопроизводительный приложений.
Cron сравнительно проще, ведь из себя он представляет фоновый процесс, выполняющий указанные в конфиге
команды в указанное время. И cron подходит для простых задач - очистка /tmp, создание бекапа и т.д.
Но использование Cron позволительно в рамках RPI, но изначальная идея не подходит для бота.
Если pid 1 в используемом дистрибутиве GNU/Linux - это systemd, то для обеспечения бесперерывной работы
бота лучше всего написать своего systemd daemon. Его преимущество заключается в доступности из коробки и в 
простоте обслуживания.

### Создание systemd daemon для бота
В ```/etc/systemd/system``` необходимо создать файл avito-qa-bot.service, примерно следующего
содержания. Структура простая и интуитивная. Однако стоит обратить внимание на 2 особенности:
- следует использовать абсолютные пути
- бот запускается интерпретатором из виртуального окружения
```
[Unit]
Description=Avito QA Telegram Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=lain
WorkingDirectory=/home/lain/apps/avito-qa
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/lain/apps/avito-qa/venv/bin/python /home/lain/apps/avito-qa/bot.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### Starting daemon
```bash
sudo systemctl daemon-reload               #обновление информации о существующих демонах
sudo systemctl enable avito-qa-bot.service #автозапуск демона во время загрузки ОС
sudo systemctl start avito-qa-bot.service  #запуск демона
sudo systemctl status avito-qa-bot.service #проверка работает ли он
```

