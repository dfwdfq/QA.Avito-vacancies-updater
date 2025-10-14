import ssl
import re

from dataclasses import dataclass
from html import escape as html_escape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from conf import MAX_RESPONSE_SIZE, _shutdown_requested


try:
    import certifi  
except Exception:
    certifi = None  # type: ignore


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

