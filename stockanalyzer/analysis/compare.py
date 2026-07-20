"""검색으로 선택한 종목들의 기간별(1/3/7/30일) 비교 분석.
지정한 기간 전체의 종목토론실 게시글을 최대한 다 모아서(개수 제한보다 기간을 우선) 긍정/부정을
합산하고, 그 기간 동안 실제 주가가 오르내린 방향과 단순 비교한다.
('오늘 여론 -> 내일 수익률' 같은 일별 상관관계가 아니라, '기간 전체 여론 우세 방향 vs 기간 전체 등락 방향'을 비교하는 방식이다.)"""
from datetime import datetime, timedelta

from stockanalyzer.crawler.fundamentals import fetch_per_pbr
from stockanalyzer.crawler.community import fetch_board_posts_since
from stockanalyzer.crawler.news import fetch_news_posts_since
from stockanalyzer.crawler.price import fetch_price_history
from stockanalyzer.analysis.sentiment import score_posts

PRICE_LOOKBACK_PAGES = 5   # sise_day.naver 페이지 수 (약 50거래일치, 30일 창까지 넉넉히 커버)

# 게시글 수 자체보다 '지정 기간 끝까지 도달하는 것'이 우선이라, 상한은 사실상 안전장치 용도로만 크게 잡는다.
# (인기 종목이라도 왠만한 기간은 이 안에서 끝나지만, 최악의 경우에도 무한루프는 되지 않도록 막아둔다.)
BOARD_MAX_PAGES = 1000
NEWS_MAX_PAGES = 150  # 네이버 뉴스 API도 150페이지 이후로는 빈 결과만 돌아옴(자체 상한)


def _tally(posts: list) -> dict:
    """점수가 매겨진 게시글 리스트에서 긍정/부정/중립 개수를 센다."""
    pos = sum(1 for p in posts if p["sentiment_label"] == "긍정")
    neg = sum(1 for p in posts if p["sentiment_label"] == "부정")
    neutral = sum(1 for p in posts if p["sentiment_label"] == "중립")
    total = len(posts)
    return {
        "total_posts": total,
        "pos_count": pos,
        "neg_count": neg,
        "neutral_count": neutral,
        "pos_ratio": round(pos / total * 100, 1) if total else None,
        "neg_ratio": round(neg / total * 100, 1) if total else None,
    }


def _judge(pos: int, neg: int, price_change_pct):
    """기간 전체 여론(긍정/부정 합계 우세)과 실제 등락 방향을 단순 비교한다."""
    if price_change_pct is None or (pos == 0 and neg == 0):
        return {"sentiment_majority": None, "price_direction": None, "match": None}

    if pos == neg:
        sentiment_majority = "동률"
    else:
        sentiment_majority = "긍정" if pos > neg else "부정"

    price_direction = "상승" if price_change_pct > 0 else ("하락" if price_change_pct < 0 else "보합")

    if sentiment_majority == "동률" or price_direction == "보합":
        match = None
    else:
        match = (sentiment_majority == "긍정" and price_direction == "상승") or (
            sentiment_majority == "부정" and price_direction == "하락"
        )

    return {"sentiment_majority": sentiment_majority, "price_direction": price_direction, "match": match}


def analyze_stock_window(code: str, name: str, days: int = 1) -> dict:
    """단일 종목에 대해 최근 `days`일 전체의 지표를 계산한다."""
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    per_pbr = fetch_per_pbr(code)

    naver_posts, covered_full_window = fetch_board_posts_since(code, since_date, max_pages=BOARD_MAX_PAGES)
    naver_posts = score_posts(naver_posts)
    naver_tally = _tally(naver_posts)
    pos, neg = naver_tally["pos_count"], naver_tally["neg_count"]

    news_posts, news_covered_full_window = fetch_news_posts_since(code, since_date, max_pages=NEWS_MAX_PAGES)
    news_posts = score_posts(news_posts)
    news_tally = _tally(news_posts)

    price_rows = fetch_price_history(code, pages=PRICE_LOOKBACK_PAGES)
    window_rows = sorted([r for r in price_rows if r["date"] >= since_date], key=lambda r: r["date"])
    if window_rows:
        baseline, latest = window_rows[0]["close"], window_rows[-1]["close"]
    elif price_rows:
        latest, baseline = price_rows[0]["close"], price_rows[-1]["close"]
    else:
        latest = baseline = None

    price_change_pct = (
        round((latest - baseline) / baseline * 100, 2) if baseline and latest is not None else None
    )

    judgement = _judge(pos, neg, price_change_pct)

    result = {
        "code": code,
        "name": name,
        "per": per_pbr["per"],
        "pbr": per_pbr["pbr"],
        "price_now": latest,
        "price_change_pct": price_change_pct,
        "window_days": days,
        "covered_full_window": covered_full_window,
        "sentiment_majority": judgement["sentiment_majority"],
        "price_direction": judgement["price_direction"],
        "match": judgement["match"],
        **naver_tally,
        # 뉴스(네이버 증권 뉴스 API) 집계는 news_ 접두어로 별도 제공. "여론-실제 일치" 판정에는
        # 쓰지 않고, 커뮤니티 여론과 나란히 비교해 보여주는 용도로만 사용한다.
        "news_covered_full_window": news_covered_full_window,
        "news_total_posts": news_tally["total_posts"],
        "news_pos_count": news_tally["pos_count"],
        "news_neg_count": news_tally["neg_count"],
        "news_neutral_count": news_tally["neutral_count"],
        "news_pos_ratio": news_tally["pos_ratio"],
        "news_neg_ratio": news_tally["neg_ratio"],
    }
    return result
