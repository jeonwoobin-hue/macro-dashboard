"""검색으로 선택한 종목들의 기간별(1/3/5/10/20일) 비교 분석.
지정한 기간 전체의 종목토론실 게시글을 최대한 다 모아서(개수 제한보다 기간을 우선) 긍정/부정을
합산하고, 그 기간 동안 실제 주가가 오르내린 방향과 단순 비교한다.
('오늘 여론 -> 내일 수익률' 같은 일별 상관관계가 아니라, '기간 전체 여론 우세 방향 vs 기간 전체 등락 방향'을 비교하는 방식이다.)

일자별 트렌드(daily_sentiment/daily_price_changes)는 이 기간 전체 판정과 별개로 함께 계산해서
결과에 담아둔다 — 일별 상세 테이블/차트, 시차(lag) 옵션 토글, 개미 지수(적중률) 계산에 재사용하기
위함이며, 크롤링은 한 번만 하고 lag 옵션을 바꿀 때는 build_daily_table을 다시 부르기만 하면 된다."""
from datetime import datetime, timedelta

from stockanalyzer.crawler.fundamentals import fetch_per_pbr
from stockanalyzer.crawler.community import fetch_board_posts_since
from stockanalyzer.crawler.news import fetch_news_posts_since
from stockanalyzer.crawler.price import fetch_price_history
from stockanalyzer.analysis.sentiment import score_posts, daily_sentiment_summary, top_keywords

PRICE_LOOKBACK_PAGES = 5   # sise_day.naver 페이지 수 (약 50거래일치, 30일 창까지 넉넉히 커버)

# 게시글 수 자체보다 '지정 기간 끝까지 도달하는 것'이 우선이라, 상한은 사실상 안전장치 용도로만 크게 잡는다.
# (인기 종목이라도 왠만한 기간은 이 안에서 끝나지만, 최악의 경우에도 무한루프는 되지 않도록 막아둔다.)
BOARD_MAX_PAGES = 1000
NEWS_MAX_PAGES = 150  # 네이버 뉴스 API도 150페이지 이후로는 빈 결과만 돌아옴(자체 상한)

MIN_DAILY_BUZZ = 20      # 이 미만이면 소수 게시글에 좌우된 판정이라 '신뢰도 미달'로 표시
BUZZ_SPIKE_RATIO = 2.0   # 그 날 게시글 수가 창 내 중앙값의 이 배수를 넘으면 '버즈 급증'으로 표시


def daily_price_changes(price_rows: list, since_date: str) -> list:
    """가격 이력(최신순)에서 since_date 이전 하루치까지 포함해 일자별 전일 대비 등락률(%)을
    오래된 날짜 순으로 반환한다. since_date 이전 하루가 있어야 since_date 당일의 등락률을 계산할
    수 있어서, 자르기 전에 등락률부터 계산한다."""
    rows = sorted(price_rows, key=lambda r: r["date"])
    changes = []
    for i in range(1, len(rows)):
        prev_close, close = rows[i - 1]["close"], rows[i]["close"]
        if not prev_close or close is None:
            continue
        changes.append({
            "date": rows[i]["date"],
            "price_change_pct": round((close - prev_close) / prev_close * 100, 2),
        })
    return [c for c in changes if c["date"] >= since_date]


def build_daily_table(daily_sentiment: dict, price_changes: list, lag_days: int = 0) -> list:
    """일자별 여론(daily_sentiment) + 일자별 등락률(price_changes)을 합쳐 날짜순 상세 행을 만든다.
    lag_days=0이면 '당일 여론 vs 당일 등락', lag_days=1이면 '당일 여론 vs 다음 거래일 등락'으로
    비교한다(다음 거래일은 실제 거래일 목록 기준이라 주말/공휴일을 자동으로 건너뛴다)."""
    trading_dates = sorted({c["date"] for c in price_changes})
    price_by_date = {c["date"]: c["price_change_pct"] for c in price_changes}

    buzz_totals = [b["total"] for b in daily_sentiment.values() if b["total"]]
    buzz_median = sorted(buzz_totals)[len(buzz_totals) // 2] if buzz_totals else 0

    rows = []
    for date in sorted(daily_sentiment.keys()):
        bucket = daily_sentiment[date]
        pos, neg, total = bucket["pos"], bucket["neg"], bucket["total"]
        majority = None
        if total:
            majority = "긍정" if pos > neg else ("부정" if neg > pos else "동률")

        target_date = date
        if lag_days:
            later = [d for d in trading_dates if d > date]
            target_date = later[0] if later else None

        price_change_pct = price_by_date.get(target_date) if target_date else None
        match = None
        if price_change_pct is not None and majority not in (None, "동률") and price_change_pct != 0:
            price_direction_up = price_change_pct > 0
            match = (majority == "긍정") == price_direction_up

        rows.append({
            "date": date,
            "pos_count": pos,
            "neg_count": neg,
            "neutral_count": bucket["neutral"],
            "total_posts": total,
            "pos_ratio": round(pos / total * 100, 1) if total else None,
            "majority": majority,
            "price_change_pct": price_change_pct,
            "match": match,
            "low_buzz": total < MIN_DAILY_BUZZ,
            "buzz_spike": bool(buzz_median) and total >= buzz_median * BUZZ_SPIKE_RATIO,
        })
    return rows


def compute_hit_rate(daily_rows: list) -> dict:
    """low_buzz(신뢰도 미달)인 날은 제외하고, match가 결정된 날들 중 일치 비율(개미 지수)을 계산한다."""
    judged = [r for r in daily_rows if r["match"] is not None and not r["low_buzz"]]
    if not judged:
        return {"hit_rate": None, "judged_days": 0}
    hits = sum(1 for r in judged if r["match"])
    return {"hit_rate": round(hits / len(judged) * 100, 1), "judged_days": len(judged)}


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
    """단일 종목에 대해 최근 `days`거래일 전체의 지표를 계산한다.
    달력일이 아니라 실제 거래일(주말·공휴일 제외) 기준으로 기간을 잡는다 — price_rows 자체가
    네이버 시세 페이지에서 실제로 장이 열렸던 날짜만 담고 있으므로, 그 목록에서 최근 N개를
    세어 since_date를 정하면 자연히 휴장일이 빠진다(예: 최근 10일 선택 시 공휴일·주말은 건너뛰고
    실제로 거래된 10개 날짜만 집계)."""
    per_pbr = fetch_per_pbr(code)

    price_rows = fetch_price_history(code, pages=PRICE_LOOKBACK_PAGES)
    trading_dates = sorted({r["date"] for r in price_rows if r.get("close") is not None}, reverse=True)
    if len(trading_dates) >= days:
        since_date = trading_dates[days - 1]
    elif trading_dates:
        since_date = trading_dates[-1]
    else:
        # 시세를 아예 못 가져온 예외적인 경우에만 달력일로 대체
        since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    naver_posts, covered_full_window = fetch_board_posts_since(code, since_date, max_pages=BOARD_MAX_PAGES)
    naver_posts = score_posts(naver_posts)
    naver_tally = _tally(naver_posts)
    pos, neg = naver_tally["pos_count"], naver_tally["neg_count"]

    news_posts, news_covered_full_window = fetch_news_posts_since(code, since_date, max_pages=NEWS_MAX_PAGES)
    news_posts = score_posts(news_posts)
    news_tally = _tally(news_posts)

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

    daily_sentiment = daily_sentiment_summary(naver_posts)
    daily_prices = daily_price_changes(price_rows, since_date)
    daily_rows = build_daily_table(daily_sentiment, daily_prices, lag_days=0)
    hit_rate = compute_hit_rate(daily_rows)

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
        # 일별 트렌드 원재료. app.py에서 lag 옵션 토글 시 재크롤링 없이 build_daily_table을
        # 다시 호출해 재계산한다.
        "daily_sentiment": daily_sentiment,
        "daily_price_changes": daily_prices,
        "hit_rate": hit_rate["hit_rate"],
        "hit_rate_judged_days": hit_rate["judged_days"],
        "top_keywords_pos": top_keywords(naver_posts, "긍정"),
        "top_keywords_neg": top_keywords(naver_posts, "부정"),
        **naver_tally,
        # 원문 데이터 노출용 표본(최신순 최대 50건). 전체 게시글을 다 저장하면
        # 인기 종목은 JSON이 지나치게 커져서 미리보기 용도로만 개수를 제한한다.
        "posts_sample": [
            {"date": p["date"], "title": p["title"], "label": p["sentiment_label"]}
            for p in naver_posts[:50]
        ],
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
