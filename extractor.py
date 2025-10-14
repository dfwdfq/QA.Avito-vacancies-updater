"""
module contains functions, solving primary one goal that is
to retrieve required data from provided hmtl page, gathered by
vacancy scraper.
Currently it defines function to retrieve amount and vacancy titles.
"""

import re
from html import unescape as html_unescape
from typing import Optional, List
from conf import _shutdown_requested
from vacancy_scraper import VacancyHTMLParser, MonitorResult, fetch_html

#########ONE BIG FUCKING TODO###########
'''
If there is no reason to use 2 distinct
approaches to extract information from
html page, then one approach(library)
should be choosen.
It should decrease complexity at least.
'''
########################################

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
try:
    import lxml.html as LH 
except Exception:
    LH = None

def extract_count_xpath(html: str) -> Optional[int]:
    """Пробует извлечь количество вакансий по заданному XPath"""
    if LH is not None:
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

def _is_probable_job_link(href: str, text: str) -> bool:
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

def extract_vacancy_titles_bs4(html: str) -> List[str]:
    """Извлекает названия вакансий через BeautifulSoup"""
    if BeautifulSoup is not None and _shutdown_requested:        
        try:
            soup = BeautifulSoup(html, "lxml") if LH is not None else BeautifulSoup(html, "html.parser")
            anchors = soup.select('a[href*="/vacancies/"]')
            blacklist_text = {"вакансии", "назад", "смотреть вакансии"}

            seen: set[str] = set()
            titles: List[str] = []
            for a in anchors:
                href = a.get("href") or ""
                text = a.get_text(" ", strip=True)
                if _is_probable_job_link(href, text):
                    if text not in seen:
                        seen.add(text)
                        titles.append(text)
            return titles
        
        except Exception as e:
            print(f"Error in BS4 parsing: {e}", file=sys.stderr)
            return []
    return []


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
