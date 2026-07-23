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


def _find_row_values(soup, header_text: str):
    """'기업실적분석' 표에서 헤더 텍스트가 정확히 일치하는 <th>가 속한 행의 <td> 값들을
    시간순(과거->최근)으로 반환한다. 표의 정확한 id/class 구조는 변동 가능성이 있어,
    구조 대신 헤더 텍스트로 찾는 방식이 더 안정적이다."""
    for th in soup.find_all("th"):
        if th.get_text(strip=True) == header_text:
            tr = th.find_parent("tr")
            if tr:
                return [parse_number(td.get_text()) for td in tr.find_all("td")]
    return []


def _last_valid(values):
    for v in reversed(values):
        if v is not None:
            return v
    return None


def _last_two_valid(values):
    valid = [v for v in values if v is not None]
    return (valid + [None, None])[-2:] if len(valid) < 2 else valid[-2:]


def fetch_fundamentals_extended(code: str):
    """업종분석 고도화용 확장 재무지표. main.naver 한 페이지에서 PER/PBR과 함께
    시가총액(억원)·ROE(%)·부채비율(%)·EPS 성장률(%, 최근 두 연간 실적 비교)을 추출한다.
    '기업실적분석' 비교표에 없는 지표(EV/EBITDA, FCF 등)는 제공하지 않는다 — 네이버
    금융에서 안정적으로 크롤링 가능한 형태로 노출되지 않기 때문(가치점수 산식에서 제외,
    나머지 지표 가중치를 비례 재조정해 사용).
    항목이 없거나 페이지 구조가 달라 못 찾으면 해당 값은 None으로 채워 반환한다."""
    soup = get_soup(MAIN_URL.format(code=code))
    per_el = soup.select_one("#_per")
    pbr_el = soup.select_one("#_pbr")
    market_cap_el = soup.select_one("#_market_sum")

    roe_values = _find_row_values(soup, "ROE(지배주주)") or _find_row_values(soup, "ROE")
    debt_values = _find_row_values(soup, "부채비율")
    eps_values = _find_row_values(soup, "EPS(원)") or _find_row_values(soup, "EPS")

    eps_prev, eps_latest = _last_two_valid(eps_values)
    eps_growth = None
    if eps_prev is not None and eps_latest is not None and eps_prev != 0:
        eps_growth = round((eps_latest - eps_prev) / abs(eps_prev) * 100, 2)

    return {
        "per": parse_number(per_el.text) if per_el else None,
        "pbr": parse_number(pbr_el.text) if pbr_el else None,
        "market_cap": parse_number(market_cap_el.text) if market_cap_el else None,
        "roe": _last_valid(roe_values),
        "debt_ratio": _last_valid(debt_values),
        "eps_growth": eps_growth,
    }
