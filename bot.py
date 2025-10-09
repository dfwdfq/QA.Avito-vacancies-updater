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
    last_update_id: Optional[int]
    lock: threading.Lock


def load_state() -> BotState:
    raw = _read_json_file(SUBSCRIPTIONS_FILE)
    if not raw:
        return BotState(subscribed_chat_ids=set(), last_update_id=None, lock=threading.Lock())
    chats = set()
    for v in raw.get("subscribed_chat_ids", []):
        try:
            chats.add(int(v))
        except Exception:
            continue
    last_update_id = raw.get("last_update_id")
    try:
        last_update_id = int(last_update_id) if last_update_id is not None else None
    except Exception:
        last_update_id = None
    return BotState(subscribed_chat_ids=chats, last_update_id=last_update_id, lock=threading.Lock())


def save_state(state: BotState) -> None:
    with state.lock:
        data = {
            "subscribed_chat_ids": sorted(list(state.subscribed_chat_ids)),
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
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not isinstance(chat_id, int):
        return

    if text == "/start":
        with state.lock:
            state.subscribed_chat_ids.add(chat_id)
        save_state(state)
        send_telegram_message(token, str(chat_id), "Подписка активирована. Буду присылать сводку каждые 15 минут.")
        # Можно сразу отправить первое сообщение
        try:
            result = monitor(AVITO_URL)
            msg = format_telegram_summary(result, AVITO_URL)
            send_telegram_message(token, str(chat_id), msg)
        except Exception as e:
            send_telegram_message(token, str(chat_id), f"Не удалось выполнить мониторинг: {e}")
        return

    if text == "/stop":
        with state.lock:
            state.subscribed_chat_ids.discard(chat_id)
        save_state(state)
        send_telegram_message(token, str(chat_id), "Подписка остановлена. Команда /start — чтобы возобновить.")
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
    interval_sec = 15 * 60
    # Первый запуск через полный интервал, чтобы не дублировать мгновенную отправку из /start
    next_run = time.monotonic() + interval_sec
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= next_run:
            try:
                result = monitor(AVITO_URL)
                msg = format_telegram_summary(result, AVITO_URL)
                with state.lock:
                    chat_ids = list(state.subscribed_chat_ids)
                for chat_id in chat_ids:
                    send_telegram_message(token, str(chat_id), msg)
            except Exception as e:
                print(f"Ошибка планировщика: {e}", file=sys.stderr)
            next_run = now + interval_sec
        # Небольшой сон, чтобы не грузить CPU
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


