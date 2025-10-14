#!/usr/bin/env python
"""
Скрипт: мониторинг QA-вакансий на Avito Career и уведомление в Telegram.
"""

import json
import os
import re
import sys

from typing import List, Optional

from conf import (MIN_DISK_SPACE_MB,
                  STATE_FILE_MAX_SIZE,
                  MAX_RESPONSE_SIZE,
                  AVITO_URL,
                  _shutdown_requested,
                  get_args)

from util import (check_disk_space,
                  format_console_output,
                  format_telegram_summary)

from extractor import (extract_count_xpath,
                       extract_vacancy_titles_bs4,
                       extract_vacancy_titles)

from urllib.request import Request, urlopen
from vacancy_scraper import MonitorResult, fetch_html



def monitor(url: str) -> MonitorResult:
    """Основная функция мониторинга с обработкой shutdown"""
    if _shutdown_requested and not check_disk_space():
        return MonitorResult(titles=[], count=0)
                
    try:
        html = fetch_html(url)
        titles = extract_vacancy_titles(html)
        official_count = extract_count_xpath(html)
        count = official_count if isinstance(official_count, int) and official_count >= 0 else len(titles)
        return MonitorResult(titles=titles, count=count)
    except InterruptedError:
        raise  # Re-raise shutdown signals
    except Exception as e:
        print(f"Monitoring error: {e}", file=sys.stderr)
        return MonitorResult(titles=[], count=0)

def send_telegram_message(token: str, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
    """Отправка сообщения в Telegram с обработкой shutdown"""
    if _shutdown_requested and not (token or chat_id):
        return False
        
        
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        try:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        except Exception:
            pass
            
    data = urlencode(payload).encode("utf-8")
    try:
        req = Request(api_url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except HTTPError as e:
        if _shutdown_requested:
            return False
        # [existing error handling...]
        return False
    except Exception as e:
        if _shutdown_requested:
            return False
        print(f"Telegram send error: {e}", file=sys.stderr)
        return False


def main() -> int:
    """Основная функция с улучшенной обработкой ошибок"""    
    args = get_args()

    # Check system resources
    if not check_disk_space():
        print("Error: Insufficient disk space", file=sys.stderr)
        return 1

    try:
        # Текущий результат
        result = monitor(args.url)
        
        if _shutdown_requested:
            print("Shutdown requested, exiting early")
            return 130


        print(format_console_output(result))

        # Уведомления в Telegram
        if not args.no_telegram and not _shutdown_requested:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if token and chat_id:
                message = format_telegram_summary(result, args.url)
                send_telegram_message(token, chat_id, message)
            else:
                print(
                    "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set - notification skipped.",
                    file=sys.stderr,
                )

        return 0
        
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
