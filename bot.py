#!/usr/bin/env python
"""
Telegram-бот для мониторинга QA-вакансий.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from urllib.parse import urlencode
from urllib.request import Request, urlopen

from conf import (MIN_DISK_SPACE_MB,
                  STATE_FILE_MAX_SIZE,
                  SUBSCRIPTIONS_FILE)

from util import (register_signal_handlers,
                  check_disk_space,
                  format_telegram_summary,
                  _shutdown_requested,
                  load_env_variables,
                  check_state_file_size)


# Импортируем логику мониторинга
from search_qa import  monitor,send_telegram_message

from bot_state import (BotState,
                       load_state,
                       save_state,
                       create_empty_state)

register_signal_handlers()
load_env_variables()


def telegram_api_call(token: str,
                      method: str,
                      params: Optional[Dict[str, Any]] = None,
                      timeout: int = 60) -> Dict[str, Any]:
    """Вызов Telegram Bot API с обработкой shutdown"""
    if _shutdown_requested:
        return {"ok": False, "error": "shutdown"}
        
    base = f"https://api.telegram.org/bot{token}/{method}"
    url = base
    data_bytes = None
    headers = {}
    
    if params:
        if method == "getUpdates":
            qs = urlencode(params)
            url = f"{base}?{qs}"
        else:
            data_bytes = urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            
    req = Request(url, data=data_bytes, method="POST" if data_bytes else "GET")
    for k, v in headers.items():
        req.add_header(k, v)
        
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "error": "bad-json", "raw": raw}
    except Exception as e:
        if _shutdown_requested:
            return {"ok": False, "error": "shutdown"}
        return {"ok": False, "error": str(e)}

def handle_update(state: BotState,
                  token: str,
                  upd: Dict[str, Any]) -> None:
    """Обработка обновлений от Telegram"""
    if _shutdown_requested:
        return
        
    message = upd.get("message") or upd.get("edited_message")
    callback_query = upd.get("callback_query")

    if isinstance(callback_query, dict):
        data = callback_query.get("data") or ""
        msg = callback_query.get("message") or {}
        chat = (msg.get("chat") or {})
        chat_id = chat.get("id")
        if isinstance(chat_id, int) and data:
            on_callback(state, token, chat_id, str(data))
        return

    if not isinstance(message, dict):
        return
        
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not isinstance(chat_id, int):
        return

    if text == "/start":
        show_main_menu(token, chat_id)
        return

    if text == "/stop":
        with state.lock:
            state.subscribed_chat_ids.discard(chat_id)
            state.chat_period_sec.pop(chat_id, None)
            state.chat_next_run.pop(chat_id, None)
        save_state(state)
        send_telegram_message(token, str(chat_id), "Подписка остановлена. Команда /start — чтобы открыть меню.")
        return

def show_main_menu(token: str,
                   chat_id: int) -> None:
    """Показать главное меню"""
    kb = {
        "inline_keyboard": [
            [
                {"text": "Включить отслеживание", "callback_data": "enable"},
                {"text": "Отключить", "callback_data": "disable"},
            ]
        ]
    }
    send_telegram_message(token, str(chat_id), "Выберите действие:", reply_markup=kb)

def show_period_menu(token: str,
                     chat_id: int) -> None:
    """Показать меню выбора периода"""
    options = [
        ("Каждые 15 минут", 15 * 60),
        ("Каждый час", 60 * 60),
        ("Каждые 6 часов", 6 * 60 * 60),
        ("Каждые 12 часов", 12 * 60 * 60),
        ("Раз в сутки", 24 * 60 * 60),
    ]
    rows = []
    for text, sec in options:
        rows.append([{ "text": text, "callback_data": f"period:{sec}" }])
    kb = {"inline_keyboard": rows}
    send_telegram_message(token, str(chat_id), "Выберите периодичность:", reply_markup=kb)

def on_callback(state: BotState,
                token: str,
                chat_id: int,
                data: str) -> None:
    """Обработка callback-запросов"""
    if _shutdown_requested:
        return
        
    if data == "enable":
        show_period_menu(token, chat_id)
        return
        
    if data == "disable":
        with state.lock:
            state.subscribed_chat_ids.discard(chat_id)
            state.chat_period_sec.pop(chat_id, None)
            state.chat_next_run.pop(chat_id, None)
        save_state(state)
        send_telegram_message(token, str(chat_id), "Подписка отключена.")
        return
        
    if data.startswith("period:"):
        try:
            sec = int(data.split(":", 1)[1])
        except Exception:
            send_telegram_message(token, str(chat_id), "Некорректный период.")
            return
            
        now = time.monotonic()
        with state.lock:
            state.subscribed_chat_ids.add(chat_id)
            state.chat_period_sec[chat_id] = sec
            state.chat_next_run[chat_id] = now + sec
            
        save_state(state)
        send_telegram_message(token, str(chat_id), f"Готово. Буду присылать каждые {sec // 60} минут.")
        
        # Сразу покажем актуальную сводку
        try:
            result = monitor(AVITO_URL)
            msg = format_telegram_summary(result, AVITO_URL)
            send_telegram_message(token, str(chat_id), msg)
        except Exception as e:
            send_telegram_message(token, str(chat_id), f"Не удалось выполнить мониторинг: {e}")
        return

def polling_loop(state: BotState,
                 token: str,
                 stop_event: threading.Event) -> None:
    """Цикл опроса Telegram API"""
    while not stop_event.is_set() and not _shutdown_requested:
        params = {"timeout": 50}
        with state.lock:
            if state.last_update_id is not None:
                params["offset"] = state.last_update_id + 1
                
        try:
            data = telegram_api_call(token, "getUpdates", params=params, timeout=60)
            if not isinstance(data, dict) or not data.get("ok"):
                time.sleep(2)
                continue
                
            updates: List[Dict[str, Any]] = data.get("result") or []
            for upd in updates:
                if stop_event.is_set() or _shutdown_requested:
                    break
                try:
                    upd_id = int(upd.get("update_id"))
                except Exception:
                    continue
                    
                with state.lock:
                    state.last_update_id = upd_id
                handle_update(state, token, upd)
                
            if updates and not _shutdown_requested:
                save_state(state)
                
        except Exception as e:
            if not _shutdown_requested:
                print(f"Polling error: {e}", file=sys.stderr)
            time.sleep(3)

def scheduler_loop(state: BotState,
                   token: str,
                   stop_event: threading.Event) -> None:
    """Цикл планировщика для отправки уведомлений"""
    while not stop_event.is_set() and not _shutdown_requested:
        now = time.monotonic()
        try:
            with state.lock:
                items = list(state.chat_next_run.items())
        except Exception:
            items = []
            
        for chat_id, ts in items:
            if stop_event.is_set() or _shutdown_requested:
                break
                
            if now >= ts:
                try:
                    result = monitor(AVITO_URL)
                    if _shutdown_requested:
                        break
                    msg = format_telegram_summary(result, AVITO_URL)
                    send_telegram_message(token, str(chat_id), msg)
                except Exception as e:
                    if not _shutdown_requested:
                        print(f"Scheduler error: {e}", file=sys.stderr)
                        
                # Запланировать следующий запуск
                with state.lock:
                    sec = state.chat_period_sec.get(chat_id, 15 * 60)
                    state.chat_next_run[chat_id] = now + sec
                    
                if not _shutdown_requested:
                    save_state(state)
                    
        stop_event.wait(1.0)

def main() -> int:
    """Основная функция бота"""
    global _shutdown_requested
    
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN not set in .env/environment", file=sys.stderr)
        return 2

    # Check system resources
    if not check_disk_space():
        print("Error: Insufficient disk space", file=sys.stderr)
        return 1

    state = load_state()
    stop_event = threading.Event()

    # Запускаем потоки
    poller = threading.Thread(target=polling_loop, args=(state, token, stop_event), daemon=True)
    sched = threading.Thread(target=scheduler_loop, args=(state, token, stop_event), daemon=True)

    poller.start()
    sched.start()

    print("Бот запущен. Ожидаю команды /start в чате.")
    
    try:
        while not _shutdown_requested:
            time.sleep(0.5)
            # Проверяем, живы ли потоки
            if not poller.is_alive() or not sched.is_alive():
                print("One of the worker threads died, shutting down...", file=sys.stderr)
                break
                
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        print("Остановка...")
        stop_event.set()
        
        # Даем потокам время на завершение
        poller.join(timeout=5)
        sched.join(timeout=5)
        
        save_state(state)
        
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
