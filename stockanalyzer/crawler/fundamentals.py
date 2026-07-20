"""종목별 PER/PBR 크롤러 (네이버 금융 종목 메인 페이지)."""
from stockanalyzer.crawler.common import get_soup, parse_number

MAIN_URL = "https://finance.naver.com/item/main.naver?code={code}"


def fetch_per_pbr(code: str):
    """종목의 PER, PBR을 {'per': float|None, 'pbr': float|None} 형태로 반환한다."""
    soup = get_soup(MAIN_URL.format(code=code))
    per_el = soup.select_one("#_per")
    pbr_el = soup.select_one("#_pbr")
    return {
        "per": parse_number(per_el.text) if per_el else None,
        "pbr": parse_number(pbr_el.text) if pbr_el else None,
    }
