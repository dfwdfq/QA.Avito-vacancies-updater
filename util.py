'''
Module contains various helper functions separated by tags:
- system event handlers
  handle different signals sent to the bot

- env
  process .env

- space size checkers
  check is there enough disk space to apply operation

- Info output
  gathered information output

- File I/0
  input/output functions used to store state
'''
import signal
import os
import sys
import json
import shutil

from html import escape as html_escape
from html import escape as html_escape

from conf import MIN_DISK_SPACE_MB, _shutdown_requested, STATE_FILE_MAX_SIZE, SUBSCRIPTIONS_FILE
from vacancy_scraper import MonitorResult

from typing import Optional, Dict, Any


## system event handlers

def _shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown_requested
    _shutdown_requested = True
    print(f"Received signal {signum}, shutting down gracefully...", file=sys.stderr)
    sys.exit(0)
    
def register_signal_handlers():
    '''
    Call this function whenever you need to gently react to system signals
    '''
    signal.signal(signal.SIGINT, _shutdown_handler)  #handle ctrl+c
    signal.signal(signal.SIGTERM, _shutdown_handler) #signal sent by not user

##env
def load_env_variables():
    '''
    load data required to use telegram API
    '''
    try:
        from dotenv import load_dotenv  # type: ignore
        _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        _DOTENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
        load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
    except Exception as e:
        print(f"Error occured:{str(e)}")


## space size checkers
def check_disk_space(min_free_mb: int = MIN_DISK_SPACE_MB) -> bool:
    """Проверяет, достаточно ли свободного места на диске"""
    try:
        total, used, free = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
        free_mb = free // (1024 * 1024)
        if free_mb < min_free_mb:
            print(f"Warning: Low disk space - {free_mb}MB free, need {min_free_mb}MB", 
                  file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"Could not check disk space: {e}", file=sys.stderr)
        return True  # Continue anyway

def check_state_file_size() -> bool:
    """Проверяет размер файла состояния"""
    try:
        if os.path.exists(SUBSCRIPTIONS_FILE):
            size = os.path.getsize(SUBSCRIPTIONS_FILE)
            if size > STATE_FILE_MAX_SIZE:
                print(f"State file too large: {size} bytes", file=sys.stderr)
                return False
        return True
    except Exception:
        return True

## Info output
def format_console_output(result: MonitorResult) -> str:
    if result.count == 0:
        return "Вакансий нет"
    lines = [f"Найдено вакансий: {result.count}"]
    lines.extend(result.titles)
    return "\n".join(lines)

def format_telegram_summary(result: MonitorResult, url: str) -> str:
    if result.count == 0:
        return (
            f"<b>Avito QA вакансии</b>\n"
            f"Вакансий нет\n"
            f"Ссылка: {html_escape(url)}"
        )
    safe_titles = [html_escape(t) for t in result.titles]
    lines = [
        "<b>Avito QA вакансии</b>",
        f"Найдено вакансий: <b>{result.count}</b>",
        *safe_titles,
        f"Ссылка: {html_escape(url)}",
    ]
    return "\n".join(lines)


## File I/O
def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    """Чтение JSON файла с проверкой размера"""
    if not check_disk_space() or not check_state_file_size():
        return None
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return None

def _write_json_file(path: str, data: Dict[str, Any]) -> bool:
    """Запись JSON файла с проверкой ресурсов"""
    if _shutdown_requested:
        return False
        
    if not check_disk_space():
        print("Cannot write state: low disk space", file=sys.stderr)
        return False
        
    try:
        # Check if data would be too large
        data_size = len(json.dumps(data, ensure_ascii=False))
        if data_size > STATE_FILE_MAX_SIZE:
            print(f"State data too large: {data_size} bytes", file=sys.stderr)
            return False
            
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"Error writing {path}: {e}", file=sys.stderr)
        return False

