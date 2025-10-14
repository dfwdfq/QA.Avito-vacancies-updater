from typing import Optional

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
