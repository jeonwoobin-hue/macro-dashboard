"""네이버 금융 크롤링 공통 유틸리티."""
import time
import re

import requests
from bs4 import BeautifulSoup

from stockanalyzer.config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC

_session = requests.Session()
_session.headers.update(HEADERS)


def get_soup(url: str) -> BeautifulSoup:
    """지정 URL을 요청해 BeautifulSoup 객체로 반환한다.
    네이버 금융 페이지마다 응답 인코딩(EUC-KR/UTF-8)이 달라 Content-Type 헤더 값을 그대로 신뢰해 디코딩한다.
    과도한 요청을 막기 위해 매 호출 뒤 소폭 대기한다."""
    resp = _session.get(url, timeout=REQUEST_TIMEOUT_SEC)
    resp.raise_for_status()
    if resp.encoding is None:
        resp.encoding = resp.apparent_encoding
    time.sleep(REQUEST_DELAY_SEC)
    return BeautifulSoup(resp.text, "lxml")


def parse_number(text: str):
    """'1,234', '+2.52%', '23.04배', 'N/A' 같은 텍스트를 float로 변환한다. 변환 불가 시 None."""
    if text is None:
        return None
    cleaned = text.strip()
    cleaned = cleaned.replace(",", "").replace("%", "").replace("배", "").strip()
    if cleaned in ("", "N/A", "-", "​"):
        return None
    cleaned = re.sub(r"[^0-9.+\-]", "", cleaned)
    if cleaned in ("", "+", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(text: str):
    """'2026.07.10' 또는 '2026.07.11 12:43' 형태를 'YYYY-MM-DD' 문자열로 변환."""
    if not text:
        return None
    match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", text.strip())
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
