#!/usr/bin/env python
"""
Скрипт: мониторинг QA-вакансий на Avito Career и уведомление в Telegram.

Улучшения для Raspberry Pi:
- Ограничение размера ответа
- Обработка сигналов для graceful shutdown
- Проверка места на диске
- Улучшенная обработка ошибок
"""

import argparse
import json
import os
import re
import sys
import ssl
from typing import List, Optional

from conf import MIN_DISK_SPACE_MB, STATE_FILE_MAX_SIZE, MAX_RESPONSE_SIZE,AVITO_URL
from util import register_signal_handlers,_shutdown_requested, load_env_variables, check_disk_space
from extractor import extract_count_xpath

from urllib.request import Request, urlopen
from vacancy_page_parser import VacancyHTMLParser, MonitorResult



try:
    import certifi  
except Exception:
    certifi = None  # type: ignore

# Опциональные зависимости для улучшенного парсинга    
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None
try:
    import lxml.html as LH  # type: ignore
except Exception:
    LH = None




def extract_vacancy_titles_bs4(html: str) -> List[str]:
    """Извлекает названия вакансий через BeautifulSoup"""
    if BeautifulSoup is None: return None
    if _shutdown_requested:
        return []
        
    try:
        soup = BeautifulSoup(html, "lxml") if LH is not None else BeautifulSoup(html, "html.parser")
        anchors = soup.select('a[href*="/vacancies/"]')
        blacklist_text = {"вакансии", "назад", "смотреть вакансии"}

        def is_probable_job_link(href: str, text: str) -> bool:
            txt = (text or "").strip().lower()
            if not txt or txt in blacklist_text:
                return False
            if href.endswith("/vacancies") or href.endswith("/vacancies/"):
                return False
            if "action=filter" in href:
                return False
            if len(txt) < 5:
                return False
            path = href.split("?")[0]
            segments = [s for s in path.split("/") if s]
            if "vacancies" in segments:
                idx = segments.index("vacancies")
                return len(segments) - (idx + 1) >= 1
            return False

        seen: set[str] = set()
        titles: List[str] = []
        for a in anchors:
            if _shutdown_requested:
                break
            href = a.get("href") or ""
            text = a.get_text(" ", strip=True)
            if is_probable_job_link(href, text):
                if text not in seen:
                    seen.add(text)
                    titles.append(text)
        return titles
    except Exception as e:
        print(f"Error in BS4 parsing: {e}", file=sys.stderr)
        return []

def fetch_html(url: str, timeout: int = 25) -> str:
    """Загружает HTML с ограничением размера"""
    if _shutdown_requested:
        raise InterruptedError("Shutdown requested")
        
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
    }
    req = Request(url, headers=headers)
    
    # SSL context with size limits
    context = None
    try:
        if certifi is not None:
            context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = None
        
    try:
        with urlopen(req, timeout=timeout, context=context) as resp:
            # Check Content-Length header first
            content_length = resp.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                raise ValueError(f"Response too large: {content_length} bytes")
                
            # Read in chunks with size limit
            chunks = []
            total_size = 0
            while True:
                if _shutdown_requested:
                    raise InterruptedError("Shutdown requested")
                    
                chunk = resp.read(8192)  # 8KB chunks
                if not chunk:
                    break
                    
                total_size += len(chunk)
                if total_size > MAX_RESPONSE_SIZE:
                    raise ValueError(f"Response exceeds size limit: {total_size} > {MAX_RESPONSE_SIZE}")
                    
                chunks.append(chunk)
                
            content = b''.join(chunks)
            
            # Decode with proper charset
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", content_type, re.I)
            if m:
                charset = m.group(1)
                
            return content.decode(charset, errors="replace")
            
    except Exception as e:
        if _shutdown_requested:
            raise InterruptedError("Shutdown requested") from e
        raise

def extract_vacancy_titles(html: str) -> List[str]:
    """Извлекает названия вакансий с проверкой на shutdown"""
    if _shutdown_requested:
        return []

    # 1) Try BS4 first
    bs4_titles = extract_vacancy_titles_bs4(html)
    if bs4_titles:
        return bs4_titles

    # 2) Try JSON-LD
    seen_json = set()
    json_titles: List[str] = []
    for m in re.finditer(
        r"<script[^>]+type=\"application/ld\+json\"[^>]*>([\s\S]*?)</script>",
        html,
        re.I,
    ):
        if _shutdown_requested:
            break
        json_text = html_unescape(m.group(1)).strip()
        try:
            data = json.loads(json_text)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            context = str(item.get("@type", "")).lower()
            if "jobposting" in context or "job" in context or "vacancy" in context:
                t = item.get("jobTitle") or item.get("title")
                if isinstance(t, str):
                    tt = t.strip()
                    if tt and tt not in seen_json:
                        json_titles.append(tt)
                        seen_json.add(tt)
    if json_titles:
        return json_titles

    # 3) Fallback to HTML parser
    parser = VacancyHTMLParser()
    parser.feed(html)

    blacklist_text = {"вакансии", "назад", "смотреть вакансии"}

    def is_probable_job_link(href: str, text: str) -> bool:
        if _shutdown_requested:
            return False
        txt = text.strip().lower()
        if not txt or txt in blacklist_text:
            return False
        if href.endswith("/vacancies") or href.endswith("/vacancies/"):
            return False
        if "action=filter" in href or href.rstrip("/").endswith("/vacancies"):
            return False
        if len(text.strip()) < 5:
            return False
        try:
            path = href.split("?")[0]
            segments = [s for s in path.split("/") if s]
            if "vacancies" in segments:
                idx = segments.index("vacancies")
                return len(segments) - (idx + 1) >= 1
        except Exception:
            return False
        return False

    filtered: List[str] = []
    seen = set()
    for href, text in parser.items:
        if _shutdown_requested:
            break
        if is_probable_job_link(href, text):
            t = text.strip()
            if t and t not in seen:
                filtered.append(t)
                seen.add(t)

    return filtered

def monitor(url: str) -> MonitorResult:
    """Основная функция мониторинга с обработкой shutdown"""
    if _shutdown_requested:
        return MonitorResult(titles=[], count=0)
        
    if not check_disk_space():
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
    if _shutdown_requested:
        return False
        
    if not token or not chat_id:
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

def main(argv: Optional[List[str]] = None) -> int:
    """Основная функция с улучшенной обработкой ошибок"""
    global _shutdown_requested
    
    parser = argparse.ArgumentParser(description="Мониторинг QA-вакансий Avito Career")
    parser.add_argument("--url", default=AVITO_URL, help="URL страницы вакансий")
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Не отправлять уведомления в Telegram",
    )
    args = parser.parse_args(argv)

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

        # Вывод в консоль
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
