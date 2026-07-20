"""종목 뉴스 크롤러 (네이버 증권 stock.naver.com 뉴스 API).
finance.naver.com의 옛 뉴스 페이지(item/news_news.naver)는 네이버가 새 증권 서비스로
넘어가면서 사실상 죽어있어서, 새 서비스가 쓰는 내부 API를 대신 사용한다."""
import html
import time

from stockanalyzer.crawler.common import _session
from stockanalyzer.config import REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC

NEWS_API_URL = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=20&page={page}"


def fetch_news_posts_since(code: str, since_date: str, max_pages: int = 50):
    """since_date(YYYY-MM-DD) 이후 종목 뉴스 제목을 모을 때까지 페이지를 순회한다.
    반환: (posts, covered_full_window) — covered_full_window=False면 max_pages 안에서
    since_date까지 도달하지 못했다는 뜻(즉 실제로는 더 최신 구간만 반영된 것)."""
    posts = []
    covered_full_window = False
    for page in range(1, max_pages + 1):
        try:
            resp = _session.get(NEWS_API_URL.format(code=code, page=page), timeout=REQUEST_TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break
        time.sleep(REQUEST_DELAY_SEC)

        page_had_data = False
        page_min_date = None
        for cluster in data or []:
            for item in cluster.get("items", []):
                dt = item.get("datetime", "")
                if len(dt) < 8:
                    continue
                date = f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}"
                title = html.unescape(item.get("title", "")).strip()
                if not title:
                    continue
                page_had_data = True
                page_min_date = date if page_min_date is None else min(page_min_date, date)
                posts.append({"date": date, "title": title})

        if not page_had_data:
            covered_full_window = True
            break
        if page_min_date is not None and page_min_date < since_date:
            covered_full_window = True
            break

    posts = [p for p in posts if p["date"] >= since_date]
    return posts, covered_full_window
