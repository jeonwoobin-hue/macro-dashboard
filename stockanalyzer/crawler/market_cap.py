"""네이버 금융 시가총액 상위 종목 크롤러."""
from stockanalyzer.crawler.common import get_soup, parse_number

MARKET_CAP_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"


def fetch_top_market_cap(n: int = 10, sosok: int = 0):
    """시가총액 상위 n개 종목을 [{code, name, price, market_cap, per, roe}, ...] 형태로 반환한다.
    sosok=0: 코스피, sosok=1: 코스닥."""
    results = []
    page = 1
    while len(results) < n:
        soup = get_soup(MARKET_CAP_URL.format(sosok=sosok, page=page))
        table = soup.select_one("table.type_2")
        rows = table.select("tr")
        found_row = False
        for row in rows:
            link = row.select_one("a.tltle")
            if not link:
                continue
            found_row = True
            tds = row.select("td")
            code = link["href"].split("code=")[-1]
            results.append(
                {
                    "code": code,
                    "name": link.text.strip(),
                    "price": parse_number(tds[2].text),
                    "market_cap": parse_number(tds[6].text),  # 억원
                    "per": parse_number(tds[10].text),
                    "roe": parse_number(tds[11].text),
                }
            )
            if len(results) >= n:
                break
        if not found_row:
            break
        page += 1
    return results


def fetch_all_listed_stocks(log=None):
    """코스피(sosok=0) + 코스닥(sosok=1) 전 종목을 [{code, name, market, market_cap}] 형태로 반환한다.
    검색 캐시(stock_universe)를 만들 때 한 번만 호출하는 무거운 크롤링이다.
    market_cap(억원)은 이 목록 페이지 자체가 시가총액순 정렬이라 추가 요청 없이 같이 담아두면,
    업종분석에서 '시가총액 기준 정렬'을 할 때 종목별로 다시 크롤링하지 않고 재사용할 수 있다."""
    all_stocks = []
    for sosok, market in ((0, "KOSPI"), (1, "KOSDAQ")):
        page = 1
        while True:
            soup = get_soup(MARKET_CAP_URL.format(sosok=sosok, page=page))
            table = soup.select_one("table.type_2")
            rows = table.select("tr") if table else []
            found_row = False
            for row in rows:
                link = row.select_one("a.tltle")
                if not link:
                    continue
                found_row = True
                tds = row.select("td")
                code = link["href"].split("code=")[-1]
                all_stocks.append({
                    "code": code,
                    "name": link.text.strip(),
                    "market": market,
                    "market_cap": parse_number(tds[6].text) if len(tds) > 6 else None,
                })
            if not found_row:
                break
            if log:
                log(f"{market} {page}페이지 수집 완료 (누적 {len(all_stocks)}종목)")
            # 마지막 페이지 판별: 다음 페이지 링크가 없으면 종료
            next_exists = soup.select_one(f'a[href*="page={page + 1}"]')
            if not next_exists:
                break
            page += 1
    return all_stocks
