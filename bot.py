"""
Простой Telegram-бот (long polling), который по команде /start
подписывает чат на рассылку каждые 15 минут результатов из search_qa.py.

Требования окружения (.env):
- TELEGRAM_BOT_TOKEN

Запуск:
  python bot.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional, Set, Dict, Any, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Загружаем .env с override=True
try:
    from dotenv import load_dotenv  # type: ignore
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    _DOTENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
    load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
except Exception:
    pass

# Импортируем логику мониторинга и отправки сообщений
from search_qa import (
    AVITO_URL,
    monitor,
    format_telegram_summary,
    send_telegram_message,
)


SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_subscriptions.json")


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Не удалось прочитать {path}: {e}", file=sys.stderr)
        return None


def _write_json_file(path: str, data: Dict[str, Any]) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"Не удалось записать {path}: {e}", file=sys.stderr)


@dataclass
class BotState:
    subscribed_chat_ids: Set[int]
    # Период в секундах для каждого чата
    chat_period_sec: Dict[int, int]
    # Следующее время отправки для каждого чата (monotonic)
    chat_next_run: Dict[int, float]
    last_update_id: Optional[int]
    lock: threading.Lock


def load_state() -> BotState:
    raw = _read_json_file(SUBSCRIPTIONS_FILE)
    if not raw:
        return BotState(
            subscribed_chat_ids=set(),
            chat_period_sec={},
            chat_next_run={},
            last_update_id=None,
            lock=threading.Lock(),
        )
    chats = set()
    for v in raw.get("subscribed_chat_ids", []):
        try:
            chats.add(int(v))
        except Exception:
            continue
    periods = {}
    for k, v in (raw.get("chat_period_sec") or {}).items():
        try:
            periods[int(k)] = int(v)
        except Exception:
            continue
    next_run = {}
    for k, v in (raw.get("chat_next_run") or {}).items():
        try:
            next_run[int(k)] = float(v)
        except Exception:
            continue
    last_update_id = raw.get("last_update_id")
    try:
        last_update_id = int(last_update_id) if last_update_id is not None else None
    except Exception:
        last_update_id = None
    return BotState(
        subscribed_chat_ids=chats,
        chat_period_sec=periods,
        chat_next_run=next_run,
        last_update_id=last_update_id,
        lock=threading.Lock(),
    )


def save_state(state: BotState) -> None:
    with state.lock:
        data = {
            "subscribed_chat_ids": sorted(list(state.subscribed_chat_ids)),
            "chat_period_sec": {str(k): v for k, v in state.chat_period_sec.items()},
            "chat_next_run": {str(k): v for k, v in state.chat_next_run.items()},
            "last_update_id": state.last_update_id,
        }
    _write_json_file(SUBSCRIPTIONS_FILE, data)


def telegram_api_call(token: str, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
    """Вызов Telegram Bot API. Возвращает распарсенный JSON."""
    base = f"https://api.telegram.org/bot{token}/{method}"
    url = base
    data_bytes = None
    headers = {}
    if params:
        # GET для getUpdates (offset, timeout), POST для sendMessage
        if method == "getUpdates":
            qs = urlencode(params)
            url = f"{base}?{qs}"
        else:
            data_bytes = urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=data_bytes, method="POST" if data_bytes else "GET")
    for k, v in headers.items():
        req.add_header(k, v)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return {"ok": False, "error": "bad-json", "raw": raw}


def handle_update(state: BotState, token: str, upd: Dict[str, Any]) -> None:
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


def show_main_menu(token: str, chat_id: int) -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "Включить отслеживание", "callback_data": "enable"},
                {"text": "Отключить", "callback_data": "disable"},
            ]
        ]
    }
    send_telegram_message(token, str(chat_id), "Выберите действие:", reply_markup=kb)


def show_period_menu(token: str, chat_id: int) -> None:
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


def on_callback(state: BotState, token: str, chat_id: int, data: str) -> None:
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
            state.chat_next_run[chat_id] = now + sec  # первая отправка через выбранный период
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


def polling_loop(state: BotState, token: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        params = {"timeout": 50}
        if state.last_update_id is not None:
            params["offset"] = state.last_update_id + 1
        try:
            data = telegram_api_call(token, "getUpdates", params=params, timeout=60)
            if not isinstance(data, dict) or not data.get("ok"):
                time.sleep(2)
                continue
            updates: List[Dict[str, Any]] = data.get("result") or []
            for upd in updates:
                try:
                    upd_id = int(upd.get("update_id"))
                except Exception:
                    continue
                state.last_update_id = upd_id
                handle_update(state, token, upd)
            if updates:
                save_state(state)
        except Exception:
            time.sleep(3)


def scheduler_loop(state: BotState, token: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        now = time.monotonic()
        try:
            with state.lock:
                items = list(state.chat_next_run.items())
        except Exception:
            items = []
        for chat_id, ts in items:
            if now >= ts:
                try:
                    result = monitor(AVITO_URL)
                    msg = format_telegram_summary(result, AVITO_URL)
                    send_telegram_message(token, str(chat_id), msg)
                except Exception as e:
                    print(f"Ошибка планировщика: {e}", file=sys.stderr)
                # Запланировать следующий запуск по индивидуальному интервалу
                with state.lock:
                    sec = state.chat_period_sec.get(chat_id, 15 * 60)
                    state.chat_next_run[chat_id] = now + sec
                save_state(state)
        stop_event.wait(1.0)


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN не задан в .env/окружении", file=sys.stderr)
        return 2

    state = load_state()

    stop_event = threading.Event()
    poller = threading.Thread(target=polling_loop, args=(state, token, stop_event), daemon=True)
    sched = threading.Thread(target=scheduler_loop, args=(state, token, stop_event), daemon=True)

    poller.start()
    sched.start()

    print("Бот запущен. Ожидаю команды /start в чате.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Остановка...")
    finally:
        stop_event.set()
        poller.join(timeout=5)
        sched.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


