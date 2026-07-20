"""종목별 외국인/기관 순매수(수급) 크롤러 (네이버 금융 frgn.naver)."""
from stockanalyzer.crawler.common import get_soup, parse_number, parse_date

FRGN_URL = "https://finance.naver.com/item/frgn.naver?code={code}&page={page}"


def fetch_supply_demand(code: str, pages: int = 4):
    """일자별 [{date, close, inst_net_qty, foreign_net_qty, foreign_ratio,
    inst_net_value_est, foreign_net_value_est}] 리스트를 최신순으로 반환한다.
    거래대금(원)은 순매매거래량 x 종가로 추정한 값이다."""
    rows_out = []
    for page in range(1, pages + 1):
        soup = get_soup(FRGN_URL.format(code=code, page=page))
        tables = soup.select("table.type2")
        if len(tables) < 2:
            break
        table = tables[1]
        trs = table.select("tr")
        page_had_data = False
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 9:
                continue
            date = parse_date(tds[0].text)
            if not date:
                continue
            page_had_data = True
            close = parse_number(tds[1].text)
            inst_net_qty = parse_number(tds[5].text)
            foreign_net_qty = parse_number(tds[6].text)
            foreign_ratio = parse_number(tds[8].text)
            rows_out.append(
                {
                    "date": date,
                    "close": close,
                    "inst_net_qty": inst_net_qty,
                    "foreign_net_qty": foreign_net_qty,
                    "foreign_ratio": foreign_ratio,
                    "inst_net_value_est": (inst_net_qty or 0) * (close or 0),
                    "foreign_net_value_est": (foreign_net_qty or 0) * (close or 0),
                }
            )
        if not page_had_data:
            break
    return rows_out
