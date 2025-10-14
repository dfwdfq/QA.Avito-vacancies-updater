from dataclasses import dataclass
from html import unescape as html_unescape
from html import escape as html_escape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


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
        self.items: List[tuple[str, str]] = [] 

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
