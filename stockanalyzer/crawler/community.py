"""종목토론실 게시글 크롤러 (네이버 금융 board.naver)."""
from stockanalyzer.crawler.common import get_soup, parse_number, parse_date

BOARD_URL = "https://finance.naver.com/item/board.naver?code={code}&page={page}"


def fetch_board_posts(code: str, pages: int = 5):
    """종목토론실 게시글 [{date, title, writer, views, likes, dislikes}] 리스트를 최신순으로 반환한다."""
    posts = []
    for page in range(1, pages + 1):
        soup = get_soup(BOARD_URL.format(code=code, page=page))
        table = soup.select_one("table.type2")
        if table is None:
            break
        trs = table.select("tr")
        page_had_data = False
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 6:
                continue
            date = parse_date(tds[0].text)
            if not date:
                continue
            title_el = tds[1].select_one("a")
            title = title_el.text.strip() if title_el else tds[1].text.strip()
            if not title:
                continue
            page_had_data = True
            posts.append(
                {
                    "date": date,
                    "title": title,
                    "writer": tds[2].text.strip(),
                    "views": parse_number(tds[3].text),
                    "likes": parse_number(tds[4].text),
                    "dislikes": parse_number(tds[5].text),
                }
            )
        if not page_had_data:
            break
    return posts


def fetch_board_posts_since(code: str, since_date: str, max_pages: int = 15):
    """since_date(YYYY-MM-DD) 이후 게시글을 모을 때까지 페이지를 순회한다.
    인기 종목은 하루에도 게시글이 수백 개씩 쌓여 지정 기간을 모두 채우려면
    페이지가 매우 많아질 수 있으므로 max_pages로 상한을 둔다.
    반환: (posts, covered_full_window) — covered_full_window=False면 max_pages 안에서
    since_date까지 도달하지 못했다는 뜻(즉 실제로는 더 최신 구간만 반영된 것)."""
    posts = []
    covered_full_window = False
    for page in range(1, max_pages + 1):
        soup = get_soup(BOARD_URL.format(code=code, page=page))
        table = soup.select_one("table.type2")
        if table is None:
            break
        trs = table.select("tr")
        page_had_data = False
        page_min_date = None
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 6:
                continue
            date = parse_date(tds[0].text)
            if not date:
                continue
            title_el = tds[1].select_one("a")
            title = title_el.text.strip() if title_el else tds[1].text.strip()
            if not title:
                continue
            page_had_data = True
            page_min_date = date if page_min_date is None else min(page_min_date, date)
            posts.append(
                {
                    "date": date,
                    "title": title,
                    "writer": tds[2].text.strip(),
                    "views": parse_number(tds[3].text),
                    "likes": parse_number(tds[4].text),
                    "dislikes": parse_number(tds[5].text),
                }
            )
        if not page_had_data:
            covered_full_window = True
            break
        if page_min_date is not None and page_min_date < since_date:
            covered_full_window = True
            break
    posts = [p for p in posts if p["date"] >= since_date]
    return posts, covered_full_window
