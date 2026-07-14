"""
디시인사이드 국내주식 갤러리(krstock) 전날 게시글을 4개 시간대로 나눠
핵심 키워드를 긍정/부정으로 분류하고 점유율을 계산해 JSON으로 저장한다.

단순 키워드 사전 기반 휴리스틱이며, 정교한 NLP 감성분석이 아니다.
"""
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

KST = ZoneInfo("Asia/Seoul")
LIST_URL = "https://gall.dcinside.com/mgallery/board/lists/"
GALLERY_ID = "krstock"

MAX_PAGES = 1500
REQUEST_DELAY = 0.15
TIME_BUDGET_SEC = 1200  # 안전장치: 최대 20분. 21시간 구간을 다 훑으려면 8분/600페이지로는 부족해서 상향.

RAW_CACHE_PATH = "sentiment_raw_posts.json"
OUTPUT_PATH = "sentiment_data.json"

# (라벨, 09:00 기준 시작 오프셋(분), 종료 오프셋(분))
WINDOWS = [
    ("09:00~15:30 한국장 거래중", 0, 6 * 60 + 30),
    ("15:30~18:00 장 마감 후 분석", 6 * 60 + 30, 9 * 60),
    ("18:00~23:30 유럽장 시작", 9 * 60, 14 * 60 + 30),
    ("21:30~06:00 미국 경제지표·미국장", 12 * 60 + 30, 21 * 60),
]

POSITIVE_WORDS = [
    "상승", "급등", "반등", "호재", "강세", "매수", "익절", "돌파", "신고가", "불장",
    "떡상", "수익", "가즈아", "줍줍", "저점매수", "회복", "오른다", "오름", "먹었",
    "따상", "잭팟", "대박", "청신호", "호실적", "흑자", "훈풍", "가나요", "가즈아",
    "가는거야", "가는건가", "가는구나", "간다", "질주", "폭등", "찍고", "환호",
    "축하", "좋다", "좋네", "굿", "탈출성공", "치킨", "존버승", "가보자",
]
NEGATIVE_WORDS = [
    "하락", "급락", "폭락", "악재", "약세", "매도", "손절", "무너", "신저가", "곰장",
    "떡락", "물림", "손실", "내린다", "패닉", "고점", "위험", "불안", "폭망", "적자",
    "박살", "탈출", "망함", "개미지옥", "조정", "빠짐", "빠지네", "털렸", "터졌",
    "죽었", "죽는다", "미쳤", "미친", "지옥", "눈물", "물렸", "물타기", "존버",
    "걱정", "불장난", "개고생", "손절각", "물타야", "폭탄", "위기", "리스크",
]

TOPIC_KEYWORDS = [
    "삼성전자", "하이닉스", "SK하이닉스", "반도체", "나스닥", "다우", "코스피", "코스닥",
    "테슬라", "엔비디아", "금리", "연준", "FOMC", "환율", "관세", "AI", "이차전지",
    "2차전지", "바이오", "로봇", "방산", "조선", "은행", "현대차", "리벨리온", "퓨리오사",
    "원화", "국장", "미장", "유럽장", "달러", "채권", "국채", "인플레이션", "실적",
    "공매도", "외국인", "기관", "개미", "카카오", "네이버", "LG", "SK", "곱버스",
    "레버리지", "ETF", "선물", "옵션", "환테크", "엔화", "위안화", "금값", "은값",
    "금투자", "비트코인", "코인", "부동산", "달러환율", "무역", "중국", "일본", "트럼프",
]


def fetch_page(session: requests.Session, page: int) -> str:
    resp = session.get(
        LIST_URL,
        params={"id": GALLERY_ID, "page": page},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def parse_posts(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    for tr in soup.select("tr.ub-content"):
        data_type = tr.get("data-type") or ""
        # icon_notice: 공지, icon_recomimg/icon_recomtxt 등 "recom"이 포함된 타입: 인기글을
        # 원래 작성 시각 그대로 목록 중간에 재노출하는 행. 실제 작성일과 무관하게 끼어들어
        # (예: 2026-04 글이 7월 목록에 노출) 최솟값 기반 window_start 판정을 망가뜨리므로 제외.
        if data_type == "icon_notice" or "recom" in data_type:
            continue
        tit = tr.select_one("td.gall_tit a")
        date_el = tr.select_one("td.gall_date")
        if not tit or not date_el:
            continue
        href = tit.get("href", "")
        if "/board/view/" not in href:
            continue
        ts_str = date_el.get("title", "")
        if not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except ValueError:
            continue
        posts.append({"title": tit.get_text(strip=True), "ts": ts})
    return posts


def scrape_raw(target_date) -> dict:
    window_start = datetime(target_date.year, target_date.month, target_date.day, 9, 0, tzinfo=KST)
    window_end = window_start + timedelta(hours=21)  # 다음날 06:00

    session = requests.Session()
    all_posts = []
    started = time.time()

    for page in range(1, MAX_PAGES + 1):
        if time.time() - started > TIME_BUDGET_SEC:
            break
        html = fetch_page(session, page)
        posts = parse_posts(html)
        if not posts:
            break

        newest_ts = max(p["ts"] for p in posts)
        oldest_ts = min(p["ts"] for p in posts)

        if newest_ts >= window_start and oldest_ts <= window_end:
            all_posts.extend(p for p in posts if window_start <= p["ts"] < window_end)

        if oldest_ts < window_start:
            break

        time.sleep(REQUEST_DELAY)

    return {
        "target_date": str(target_date),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "posts": [{"title": p["title"], "ts": p["ts"].isoformat()} for p in all_posts],
    }


def load_or_scrape_raw(target_date) -> dict:
    if os.path.exists(RAW_CACHE_PATH):
        with open(RAW_CACHE_PATH, encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("target_date") == str(target_date):
            return cached
    raw = scrape_raw(target_date)
    with open(RAW_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    return raw


def classify_sentiment(title: str) -> str | None:
    pos = sum(1 for w in POSITIVE_WORDS if w in title)
    neg = sum(1 for w in NEGATIVE_WORDS if w in title)
    if pos > neg:
        return "긍정"
    if neg > pos:
        return "부정"
    return None


def bucket_for(ts: datetime, window_start: datetime) -> list[str]:
    minutes = (ts - window_start).total_seconds() / 60
    return [label for label, start_min, end_min in WINDOWS if start_min <= minutes < end_min]


def build_output(raw: dict) -> dict:
    window_start = datetime.fromisoformat(raw["window_start"])
    posts = [{"title": p["title"], "ts": datetime.fromisoformat(p["ts"])} for p in raw["posts"]]

    result = {
        "target_date": raw["target_date"],
        "window_start": raw["window_start"],
        "window_end": raw["window_end"],
        "total_posts_scanned": len(posts),
        "generated_at": datetime.now(KST).isoformat(),
        "buckets": {},
    }

    for label, _, _ in WINDOWS:
        bucket_posts = [p for p in posts if label in bucket_for(p["ts"], window_start)]
        pos_counter = Counter()
        neg_counter = Counter()
        pos_count = 0
        neg_count = 0
        for p in bucket_posts:
            sentiment = classify_sentiment(p["title"])
            if sentiment is None:
                continue
            hits = [kw for kw in TOPIC_KEYWORDS if kw in p["title"]]
            if not hits:
                continue
            if sentiment == "긍정":
                pos_count += 1
                pos_counter.update(hits)
            else:
                neg_count += 1
                neg_counter.update(hits)

        def to_ranked(counter: Counter) -> list[dict]:
            total = sum(counter.values())
            if total == 0:
                return []
            return [
                {"keyword": kw, "count": cnt, "pct": round(cnt / total * 100, 1)}
                for kw, cnt in counter.most_common(20)
            ]

        result["buckets"][label] = {
            "total_posts": len(bucket_posts),
            "positive_posts": pos_count,
            "negative_posts": neg_count,
            "positive_keywords": to_ranked(pos_counter),
            "negative_keywords": to_ranked(neg_counter),
        }

    return result


if __name__ == "__main__":
    yesterday = (datetime.now(KST) - timedelta(days=1)).date()
    raw = load_or_scrape_raw(yesterday)
    data = build_output(raw)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"scanned {data['total_posts_scanned']} posts for {data['target_date']}")
    for label, b in data["buckets"].items():
        print(f"  {label}: total={b['total_posts']} pos={b['positive_posts']} neg={b['negative_posts']}")
