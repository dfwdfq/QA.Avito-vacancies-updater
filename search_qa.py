"""
Скрипт: мониторинг QA-вакансий на Avito Career и уведомление в Telegram.

Функциональность:
- Загружает страницу вакансий по заданной ссылке (см. AVITO_URL ниже)
- Парсит названия вакансий
- Печатает в консоль количество и список названий
- При запуске отправляет сообщение в Telegram (если не указан --no-telegram)

Переменные окружения (для уведомлений в Telegram):
- TELEGRAM_BOT_TOKEN — токен бота
- TELEGRAM_CHAT_ID — ID чата/канала, куда отправлять уведомления

Зависимости (рекомендуется):
- beautifulsoup4, lxml — для точного парсинга CSS/XPath
Установка: pip install -r requirements.txt (см. OzonTech/requirements.txt)

Пример cron (запуск каждый день в 10:00):
0 10 * * * /usr/bin/env zsh -lc 'cd "$(dirname "/absolute/path/to/OzonTech/search_qa.py")" && /usr/bin/python3 "./search_qa.py" >> ./search_qa.log 2>&1'
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from html import unescape as html_unescape
from html import escape as html_escape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import ssl
try:
    import certifi  # type: ignore
except Exception:
    certifi = None  # type: ignore

# Загружаем переменные из .env (в корне проекта), значения из файла перекрывают существующие
try:
    from dotenv import load_dotenv  # type: ignore
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    _DOTENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
    load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
except Exception:
    # Библиотека необязательна: если не установлена, просто пропускаем
    pass

# Опциональные зависимости для улучшенного парсинга
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - опционально
    BeautifulSoup = None  # type: ignore

try:
    import lxml.html as LH  # type: ignore
except Exception:  # pragma: no cover - опционально
    LH = None  # type: ignore


# Целевая страница Avito Career с фильтром на QA (из описания задачи)
AVITO_URL = (
    "https://career.avito.com/vacancies/razrabotka/?q=&action=filter&direction=razrabotka&tags%5B%5D=s26502"
)


@dataclass
class MonitorResult:
    titles: List[str]
    count: int


class VacancyHTMLParser(HTMLParser):
    """HTML-парсер: собирает пары (href, текст) ссылок на вакансии."""

    def __init__(self) -> None:
        super().__init__()
        self._inside_relevant_anchor = False
        self._anchor_nesting = 0
        self._current_text_chunks: List[str] = []
        self._current_href: str = ""
        self.items: List[tuple[str, str]] = []  # (href, text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "/vacancies/" in href:
                self._inside_relevant_anchor = True
                self._anchor_nesting = 1
                self._current_text_chunks = []
                self._current_href = href
                return
        if self._inside_relevant_anchor:
            self._anchor_nesting += 1

    def handle_endtag(self, tag):
        if self._inside_relevant_anchor:
            self._anchor_nesting -= 1
            if tag == "a" and self._anchor_nesting <= 0:
                text = " ".join(" ".join(self._current_text_chunks).split())
                if text:
                    self.items.append((self._current_href, text))
                self._inside_relevant_anchor = False
                self._current_text_chunks = []
                self._current_href = ""
                self._anchor_nesting = 0

    def handle_data(self, data):
        if self._inside_relevant_anchor and data:
            self._current_text_chunks.append(data)


def extract_count_xpath(html: str) -> Optional[int]:
    """Пробует извлечь количество вакансий по заданному XPath (если доступен lxml)."""
    if LH is None:
        return None
    try:
        doc = LH.fromstring(html)
        nodes = doc.xpath('/html/body/main/div/div[2]/div/span')
        if not nodes:
            return None
        text = nodes[0].text_content().strip()
        m = re.search(r"\d+", text)
        return int(m.group(0)) if m else None
    except Exception:
        return None


def extract_vacancy_titles_bs4(html: str) -> List[str]:
    """Извлекает названия вакансий через BeautifulSoup, если доступен."""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "lxml") if LH is not None else BeautifulSoup(html, "html.parser")

    # Ищем ссылки на вакансии
    anchors = soup.select('a[href*="/vacancies/"]')
    blacklist_text = {"вакансии", "назад", "смотреть вакансии"}

    def is_probable_job_link(href: str, text: str) -> bool:
        txt = (text or "").strip().lower()
        if not txt or txt in blacklist_text:
            return False
        # Игнорируем общие/корневые ссылки раздела
        if href.endswith("/vacancies") or href.endswith("/vacancies/"):
            return False
        if "action=filter" in href:
            return False
        if len(txt) < 5:
            return False
        # Должен быть хотя бы один сегмент после /vacancies
        path = href.split("?")[0]
        segments = [s for s in path.split("/") if s]
        if "vacancies" in segments:
            idx = segments.index("vacancies")
            return len(segments) - (idx + 1) >= 1
        return False

    seen: set[str] = set()
    titles: List[str] = []
    for a in anchors:
        href = a.get("href") or ""
        text = a.get_text(" ", strip=True)
        if is_probable_job_link(href, text):
            if text not in seen:
                seen.add(text)
                titles.append(text)
    return titles


def fetch_html(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
    }
    req = Request(url, headers=headers)
    # Создаём SSLContext с CA-бандлом certifi, если доступен
    context = None
    try:
        if certifi is not None:
            context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = None
    with urlopen(req, timeout=timeout, context=context) as resp:
        content_type = resp.headers.get("Content-Type", "")
        charset = "utf-8"
        m = re.search(r"charset=([\w-]+)", content_type, re.I)
        if m:
            charset = m.group(1)
        raw = resp.read()
        return raw.decode(charset, errors="replace")


def extract_vacancy_titles(html: str) -> List[str]:
    # 0) Если доступен bs4 — используем его, как основной путь
    bs4_titles = extract_vacancy_titles_bs4(html)
    if bs4_titles:
        return bs4_titles

    # 1) Пытаемся вытащить из JSON-LD (JobPosting) — точный источник
    seen_json = set()
    json_titles: List[str] = []
    for m in re.finditer(
        r"<script[^>]+type=\"application/ld\+json\"[^>]*>([\s\S]*?)</script>",
        html,
        re.I,
    ):
        json_text = html_unescape(m.group(1)).strip()
        try:
            data = json.loads(json_text)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            # Ищем структуры JobPosting
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

    # 2) Фолбэк по ссылкам: фильтруем навигацию и общие ссылки
    parser = VacancyHTMLParser()
    parser.feed(html)

    blacklist_text = {"вакансии", "назад", "смотреть вакансии"}

    def is_probable_job_link(href: str, text: str) -> bool:
        txt = text.strip().lower()
        if not txt or txt in blacklist_text:
            return False
        # игнорируем корневые и фильтровые ссылки
        if href.endswith("/vacancies") or href.endswith("/vacancies/"):
            return False
        if "action=filter" in href or href.rstrip("/").endswith("/vacancies"):
            return False
        # требуем осмысленный заголовок
        if len(text.strip()) < 5:
            return False
        # допускаем только ссылки глубже одного сегмента, например /vacancies/.../...
        try:
            path = href.split("?")[0]
            segments = [s for s in path.split("/") if s]
            if "vacancies" in segments:
                idx = segments.index("vacancies")
                # Нужно как минимум ещё один непустой сегмент после "vacancies"
                return len(segments) - (idx + 1) >= 1
        except Exception:
            return False
        return False

    filtered: List[str] = []
    seen = set()
    for href, text in parser.items:
        if is_probable_job_link(href, text):
            t = text.strip()
            if t and t not in seen:
                filtered.append(t)
                seen.add(t)

    return filtered


def monitor(url: str) -> MonitorResult:
    html = fetch_html(url)
    titles = extract_vacancy_titles(html)
    # Пробуем достать «официальное» число вакансий с страницы
    official_count = extract_count_xpath(html)
    count = official_count if isinstance(official_count, int) and official_count >= 0 else len(titles)
    return MonitorResult(titles=titles, count=count)


def _noop() -> None:
    return None


def send_telegram_message(token: str, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
    if not token or not chat_id:
        return False
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],  # ограничим на всякий случай
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
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
            info = json.loads(body)
            desc = info.get("description") or body
        except Exception:
            desc = body or str(e)
        if e.code == 401:
            # Частая причина: неверный TELEGRAM_BOT_TOKEN или CHAT_ID. Подсказка.
            print(
                (
                    f"Не удалось отправить Telegram-уведомление: HTTP 401. {desc}\n"
                    f"Проверьте TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID."
                ),
                file=sys.stderr,
            )
        else:
            print(
                f"Не удалось отправить Telegram-уведомление: HTTP {e.code}. {desc}",
                file=sys.stderr,
            )
        return False
    except Exception as e:
        print(f"Не удалось отправить Telegram-уведомление: {e}", file=sys.stderr)
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
    parser = argparse.ArgumentParser(description="Мониторинг QA-вакансий Avito Career")
    parser.add_argument("--url", default=AVITO_URL, help="URL страницы вакансий")
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Не отправлять уведомления в Telegram",
    )
    args = parser.parse_args(argv)

    # Текущий результат
    result = monitor(args.url)

    # Вывод в консоль
    print(format_console_output(result))

    # Уведомления в Telegram
    if not args.no_telegram:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            message = format_telegram_summary(result, args.url)
            send_telegram_message(token, chat_id, message)
        else:
            print(
                "Переменные окружения TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — уведомление пропущено.",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
