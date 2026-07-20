"""종목별 일별 시세(과거 주가) 크롤러 (네이버 금융 sise_day.naver)."""
from stockanalyzer.crawler.common import get_soup, parse_number, parse_date

SISE_DAY_URL = "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}"


def fetch_price_history(code: str, pages: int = 4):
    """일자별 [{date, close, open, high, low, volume}] 리스트를 최신순으로 반환한다."""
    rows_out = []
    for page in range(1, pages + 1):
        soup = get_soup(SISE_DAY_URL.format(code=code, page=page))
        table = soup.select_one("table.type2")
        if table is None:
            break
        trs = table.select("tr")
        page_had_data = False
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 7:
                continue
            date = parse_date(tds[0].text)
            if not date:
                continue
            page_had_data = True
            rows_out.append(
                {
                    "date": date,
                    "close": parse_number(tds[1].text),
                    "open": parse_number(tds[3].text),
                    "high": parse_number(tds[4].text),
                    "low": parse_number(tds[5].text),
                    "volume": parse_number(tds[6].text),
                }
            )
        if not page_had_data:
            break
    return rows_out
