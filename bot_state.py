import sys
import threading

from typing import Optional, Set, Dict, Any, List
from dataclasses import dataclass

from conf import SUBSCRIPTIONS_FILE
import conf

from util import (_read_json_file,
                  _write_json_file,
                  check_disk_space)

@dataclass
class BotState:
    subscribed_chat_ids: Set[int]
    chat_period_sec: Dict[int, int]
    chat_next_run: Dict[int, float]
    last_update_id: Optional[int]
    lock: threading.Lock

def load_state() -> BotState:
    """Загрузка состояния с обработкой ошибок"""
    if not check_disk_space():
        print("Warning: Low disk space, using empty state", file=sys.stderr)
        return create_empty_state()
        
    raw = _read_json_file(SUBSCRIPTIONS_FILE)
    if not raw:
        return create_empty_state()
        
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

def create_empty_state() -> BotState:
    """Создает пустое состояние"""
    return BotState(
        subscribed_chat_ids=set(),
        chat_period_sec={},
        chat_next_run={},
        last_update_id=None,
        lock=threading.Lock(),
    )

def save_state(state: BotState) -> bool:
    """Сохранение состояния с блокировкой"""
    if conf._shutdown_requested:
        return False
        
    with state.lock:
        data = {
            "subscribed_chat_ids": sorted(list(state.subscribed_chat_ids)),
            "chat_period_sec": {str(k): v for k, v in state.chat_period_sec.items()},
            "chat_next_run": {str(k): v for k, v in state.chat_next_run.items()},
            "last_update_id": state.last_update_id,
        }
    return _write_json_file(SUBSCRIPTIONS_FILE, data)

