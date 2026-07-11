"""
네이버 뉴스 랭킹(언론사별 최다조회) 페이지에서 특정 날짜의 경제 관련 기사만
골라 조회수 순위 기준 Top N을 뽑는다.

네이버는 "카테고리별 통합 조회수 랭킹"을 공개 API로 제공하지 않는다
(언론사별 랭킹만 제공하며, sid1 카테고리 파라미터는 실질적으로 무시됨을 확인함).
따라서 언론사별 실제 조회수 순위(rank) 데이터를 그대로 사용하되,
경제 키워드 사전으로 제목을 걸러 경제 기사만 남기는 방식으로 근사한다.
"""
import requests
from bs4 import BeautifulSoup

RANKING_URL = "https://news.naver.com/main/ranking/popularDay.naver"

ECONOMIC_KEYWORDS = [
    "코스피", "코스닥", "증시", "주가", "주식", "환율", "금리", "물가", "인플레이션",
    "실적", "영업이익", "매출", "수출", "수입", "투자", "IPO", "상장", "공모가",
    "반도체", "경기침체", "경기회복", "경기부양", "경기전망", "경기지표", "GDP",
    "금융", "은행", "증권", "펀드", "부동산", "대출", "예금", "채권", "달러", "원화",
    "관세", "무역", "고용", "실업", "연준", "한은", "기준금리", "경제", "적자", "흑자",
    "공매도", "배당", "나스닥", "다우", "테슬라", "엔비디아", "삼성전자", "하이닉스",
    "SK하이닉스", "현대차", "카카오", "네이버", "시가총액", "상한가", "하한가",
    "급등", "급락", "증권가", "목표주가", "ADR", "매수", "매도",
]


def _is_economic(title: str) -> bool:
    return any(kw in title for kw in ECONOMIC_KEYWORDS)


def fetch_top_economic_news(date_str: str, top_n: int = 10) -> list[dict]:
    """date_str: YYYYMMDD. 해당 날짜의 언론사별 랭킹 중 경제 키워드가 포함된 기사를
    조회순위(rank) 기준으로 모아 언론사당 1건씩, 상위 top_n건을 반환한다."""
    resp = requests.get(
        RANKING_URL, params={"date": date_str}, headers={"User-Agent": "Mozilla/5.0"}, timeout=15
    )
    resp.raise_for_status()
    resp.encoding = "EUC-KR"
    soup = BeautifulSoup(resp.text, "lxml")

    candidates = []
    for box in soup.select(".rankingnews_box"):
        name_el = box.select_one(".rankingnews_name")
        press = name_el.get_text(strip=True) if name_el else "알 수 없음"
        for li in box.select(".rankingnews_list li"):
            rank_el = li.select_one(".list_ranking_num")
            title_el = li.select_one(".list_title")
            if not rank_el or not title_el:
                continue
            digits = "".join(c for c in rank_el.get_text(strip=True) if c.isdigit())
            if not digits:
                continue
            title = title_el.get_text(strip=True)
            if not _is_economic(title):
                continue
            candidates.append(
                {
                    "press": press,
                    "rank": int(digits),
                    "title": title,
                    "url": title_el.get("href", ""),
                }
            )

    candidates.sort(key=lambda c: c["rank"])

    seen_press = set()
    result = []
    for c in candidates:
        if c["press"] in seen_press:
            continue
        seen_press.add(c["press"])
        result.append(c)
        if len(result) >= top_n:
            break
    return result
