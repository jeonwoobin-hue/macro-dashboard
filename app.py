import base64
import calendar
import json
import os
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from ai_analysis import get_indicator_analysis
from charts import render_zoomable_chart, zoom_chart
from ecos_client import (
    BASE_RATE_ITEM,
    BASE_RATE_STAT_CODE,
    COINCIDENT_INDEX_ITEM,
    LEADING_INDEX_ITEM,
    fetch_ecos_monthly,
)
from fred_client import add_change_columns, fetch_fred_series
from market_data import fetch_yahoo_series
from news_client import fetch_top_economic_news
from notes_repo import TAGS as NOTE_TAGS, load_notes, note_image_data_uri

load_dotenv()

# 경제지표(물가·고용 등)는 대부분 월 1회, 청구건수는 주 1회 발표되므로 하루 한 번만
# 최신 여부를 확인해도 충분하다. FRED/ECOS 분당 호출 한도 보호 + 재배포 직후 콜드 캐시
# 상태에서의 API 호출 부담을 줄이기 위해 24시간으로 유지한다.
CACHE_TTL_SECONDS = 24 * 60 * 60

# 시장 탭(KOSPI/KOSDAQ/Nasdaq/Dow)은 각 거래소가 열려있는 시간에만 시간 단위로 갱신하고,
# 장 마감 후에는 다음 개장 전까지 마지막 종가를 그대로 캐시에 고정한다(공휴일 캘린더는
# 별도로 관리하지 않음 — 요일+시간대 기준의 근사치).
MARKET_HOURS = {
    "^KS11": ("Asia/Seoul", dtime(9, 0), dtime(15, 30)),
    "^KQ11": ("Asia/Seoul", dtime(9, 0), dtime(15, 30)),
    "^IXIC": ("America/New_York", dtime(9, 30), dtime(16, 0)),
    "^DJI": ("America/New_York", dtime(9, 30), dtime(16, 0)),
}


def market_cache_bucket(tz_name: str, open_time: dtime, close_time: dtime) -> str:
    """장중이면 시간 단위로, 장마감/휴장 중이면 마지막 거래일 종가로 캐시 키를 고정한다."""
    now_local = datetime.now(ZoneInfo(tz_name))
    is_weekday = now_local.weekday() < 5
    if is_weekday and open_time <= now_local.time() <= close_time:
        return now_local.strftime("%Y-%m-%d-%Hh")
    if is_weekday and now_local.time() > close_time:
        session_date = now_local.date()
    else:
        cand = now_local.date() - timedelta(days=1)
        while cand.weekday() >= 5:
            cand -= timedelta(days=1)
        session_date = cand
    return f"{session_date}-closed"


def get_secret(name: str) -> str:
    """로컬(.env)과 Streamlit Community Cloud(secrets.toml) 둘 다 지원."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, "")


st.set_page_config(page_title="거시경제 투자심리 대시보드", layout="wide")

# ── 가로 스크롤(3~4개 차트 카드) 전용 CSS ───────────────────
# 768px 이상(데스크톱/태블릿)에서만 가로 스크롤 적용. 그보다 좁은 화면(휴대폰)에서는
# 이 규칙이 아예 적용되지 않아 Streamlit 기본 동작대로 카드가 세로로 쌓인다.
st.markdown(
    """
    <style>
    /* 한글은 기본적으로 아무 글자 사이에서나 줄바꿈될 수 있어(예: "해석"이 "해"/"석"으로
       쪼개짐), 좁은 버튼/카드에서 단어 중간이 아니라 띄어쓰기 단위로만 줄바꿈되게 한다.
       Streamlit이 h1~h6에 자체적으로 word-break:break-word를 박아둬서, 상속만으로는
       안 먹혀 요소에 직접 !important로 덮어써야 한다. */
    div[data-testid="stAppViewContainer"],
    div[data-testid="stAppViewContainer"] h1,
    div[data-testid="stAppViewContainer"] h2,
    div[data-testid="stAppViewContainer"] h3,
    div[data-testid="stAppViewContainer"] h4,
    div[data-testid="stAppViewContainer"] p,
    div[data-testid="stAppViewContainer"] span,
    div[data-testid="stAppViewContainer"] label {
        word-break: keep-all !important;
        overflow-wrap: break-word !important;
    }

    /* 4개 카드가 나란히 놓이는 행(scrollrow)에서, 제목 글자 수가 카드마다 달라 어떤 카드는
       제목이 1줄, 어떤 카드는 2줄로 넘어가면서 그 아래 지표·차트 높이가 카드마다 어긋나
       보이던 문제 — 가장 긴 제목("신규실업수당 청구건수")도 한 줄에 들어오도록 카드 제목
       글자 크기를 살짝 줄인다(min-height로 높이만 맞추면 앵커 아이콘과의 flex 레이아웃이
       꼬여 오히려 3줄로 더 길어지는 부작용이 있었다). */
    div[class*="st-key-scrollrow"] h3 {
        font-size: 1.35rem;
    }
    /* 설명(caption) 줄 수와 st.metric의 증감(delta) 유무가 카드마다 달라서(예: BEI 카드는
       delta가 없어 metric이 더 짧음) +/- 줌 버튼과 차트 시작 위치가 카드마다 어긋났다.
       두 영역 모두 "가장 긴 경우" 기준으로 높이를 고정해 어떤 조합이 와도 정렬되게 한다. */
    div[class*="st-key-scrollrow"] [data-testid="stCaptionContainer"] {
        min-height: 5.6rem;
    }
    div[class*="st-key-scrollrow"] [data-testid="stMetric"] {
        min-height: 6.5rem;
    }
    /* D-Day 배지를 제목(h3) 안에 붙이면 카드마다 제목 길이가 달라 어떤 카드만 2줄로
       넘어가면서 위 폰트 크기 고정이 무력화되고 카드 정렬이 다시 깨졌다. 배지는 제목과
       분리해 항상 고정 높이의 별도 줄에 두면(배지가 없는 카드도 빈 줄로 같은 높이를 차지)
       제목 줄 수는 항상 동일하게 유지된다. */
    div[class*="st-key-scrollrow"] .dday-badge-line {
        min-height: 1.3rem;
        font-size: 0.8rem;
        font-weight: 700;
        color: #17A863;
        margin-bottom: 0.2rem;
    }

    @media (min-width: 768px) {
        div[class*="st-key-scrollrow"] div[data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap;
            overflow-x: auto;
            padding-bottom: 0.6rem;
        }
        div[class*="st-key-scrollrow"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 340px;
            flex: 0 0 340px;
        }
    }
    /* 참고자료1 팝오버: width= 인자는 상한일 뿐 콘텐츠가 좁으면 그대로 좁게 뜨므로,
       표가 눌리지 않도록 최소 너비를 강제한다. */
    [data-testid="stPopoverBody"] {
        min-width: min(980px, 94vw) !important;
    }

    /* Streamlit 자체 상단 툴바(≫ Deploy ⋮ 줄)도 같은 어두운 색으로 맞춘다. */
    header[data-testid="stHeader"] {
        background: #0B0F17 !important;
    }
    /* 툴바 아래 기본 여백(block-container padding-top)이 밝은 배경색으로 남아
       이음새처럼 보이던 문제 — 툴바 높이(60px)에 맞춰 줄여서 이음새를 없앤다. */
    div[data-testid="stAppViewContainer"] .block-container {
        padding-top: 2.75rem !important;
    }

    /* ── Dobio 상단 헤더(고정) ─────────────────────────────── */
    /* 끝에 공백을 붙여 "st-key-dobio_header_inner"(하위 래퍼)까지 함께 매칭되는 걸 막는다
       — 안 그러면 sticky/margin/padding이 두 컨테이너에 중복 적용돼 선이 2겹으로 보인다. */
    div[class*="st-key-dobio_header "] {
        position: sticky;
        /* Streamlit 자체 툴바(높이 60px, 항상 최상단 고정)와 겹치지 않도록 그 아래에 붙인다.
           top:0으로 두면 스크롤 시 음수 마진과 맞물려 sticky가 아예 안 먹는 버그가 있었다. */
        top: 60px;
        z-index: 999;
        background: #0B0F17;
        margin: 0 -1rem 1.1rem -1rem;
        padding: 0.7rem 1.5rem 0.9rem 1.5rem;
    }
    /* 로고 이미지를 배경으로 쓰는 '홈으로' 버튼 (텍스트 라벨은 숨김) */
    div[class*="st-key-dobio_home_btn_wrap"] button {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        opacity: 0.92;
    }
    div[class*="st-key-dobio_home_btn_wrap"] button:hover { opacity: 1; }
    div[class*="st-key-dobio_home_btn_wrap"] button p { display: none; }

    /* 헤더/본문 콘텐츠 최대폭 고정(초광폭 모니터에서도 항상 일정한 레이아웃) */
    div[class*="st-key-dobio_header_inner"] {
        max-width: 1280px;
        margin: 0 auto;
    }
    div[data-testid="stAppViewContainer"] .block-container {
        max-width: 1280px;
        margin: 0 auto;
    }

    /* 큰 내비게이션(segmented_control)을 헤더 링크처럼 보이게 재스타일링 */
    div[class*="st-key-mainnav_wrap"] [data-testid="stWidgetLabel"] {
        display: none;
    }
    div[class*="st-key-mainnav_wrap"] div[role="radiogroup"] {
        gap: 1.7rem;
        justify-content: flex-start !important;
        background: transparent !important;
        border: none !important;
        flex-wrap: wrap;
    }
    div[class*="st-key-mainnav_wrap"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0.35rem 0 !important;
        margin: 0 !important;
        border-radius: 0 !important;
        border-bottom: 2px solid transparent !important;
    }
    div[class*="st-key-mainnav_wrap"] button p {
        color: #B9C0CC !important;
        font-weight: 600 !important;
        font-size: 1.0rem !important;
    }
    div[class*="st-key-mainnav_wrap"] button:hover p { color: #FFFFFF !important; }
    div[class*="st-key-mainnav_wrap"] button[data-testid="stBaseButton-segmented_controlActive"] {
        border-bottom: 2px solid #0D6032 !important;
    }
    div[class*="st-key-mainnav_wrap"] button[data-testid="stBaseButton-segmented_controlActive"] p {
        color: #FFFFFF !important;
    }

    /* ── 히어로(투자심리 게이지 + 종목분석 검색) ───────────────── */
    div[class*="st-key-dobio_herocard"] {
        background: linear-gradient(180deg, rgba(13,96,50,0.35), rgba(15,20,30,0.15));
        border: 1px solid rgba(13,96,50,0.55);
        border-radius: 18px;
        padding: 1.3rem 1.5rem 1.0rem 1.5rem;
        margin-bottom: 1.4rem;
    }
    .dobio-gauge-title { font-size: 0.85rem; color: #9AA3B2; margin-bottom: 0.35rem; }
    .dobio-gauge-track {
        position: relative; height: 10px; border-radius: 6px; margin-top: 0.2rem;
        background: linear-gradient(90deg, #D93025 0%, #F2994A 25%, #FFD200 50%, #8BC34A 75%, #0D6032 100%);
    }
    .dobio-gauge-marker {
        position: absolute; top: -5px; width: 3px; height: 20px;
        background: #FFFFFF; border-radius: 2px; transform: translateX(-50%);
        box-shadow: 0 0 4px rgba(0,0,0,0.7);
    }
    .dobio-gauge-readout { display: flex; justify-content: space-between; align-items: baseline; margin-top: 0.4rem; }
    .dobio-gauge-score { font-size: 1.3rem; font-weight: 800; color: #EAEFF5; }
    .dobio-gauge-bucket { font-size: 0.85rem; font-weight: 700; padding: 0.12rem 0.6rem; border-radius: 999px; color: #0F141E; }
    </style>
    """,
    unsafe_allow_html=True,
)

REFERENCE_TABLE_ROWS = [
    {"지표": "Core CPI (MoM)", "핵심 정의": "에너지·식품 제외 소비자물가 전월비 변화율. 연준이 가장 주목하는 근원 인플레 지표", "최적 출처": "FRED (CPILFESL)", "수집 방식": "API (무료 키)", "발표 주기": "매월 중순"},
    {"지표": "Core PCE (MoM)", "핵심 정의": "에너지·식품 제외 개인소비지출 물가지수. 연준이 공식 타겟(2%)으로 삼는 지표", "최적 출처": "FRED (PCEPILFE)", "수집 방식": "API", "발표 주기": "매월 말"},
    {"지표": "WTI 유가", "핵심 정의": "서부텍사스산 원유 현물가($/배럴). 에너지 인플레이션과 에너지주 실적에 직결되는 선행 변수", "최적 출처": "FRED (DCOILWTICO)", "수집 방식": "API", "발표 주기": "매 영업일"},
    {"지표": "기대인플레이션 (BEI)", "핵심 정의": "국채-물가연동국채(TIPS) 스프레드로 산출한 시장 기대인플레이션(5년·10년물)", "최적 출처": "FRED (T5YIE, T10YIE)", "수집 방식": "API", "발표 주기": "매 영업일"},
    {"지표": "비농업 고용", "핵심 정의": "비농업 부문 신규 고용자 수 증감. 경기 모멘텀의 대표 선행 신호", "최적 출처": "FRED (PAYEMS)", "수집 방식": "API", "발표 주기": "매월 첫째 금요일"},
    {"지표": "실업률", "핵심 정의": "경제활동인구 중 실업자 비율. 연준 이중책무(고용) 판단 근거", "최적 출처": "FRED (UNRATE)", "수집 방식": "API", "발표 주기": "NFP와 동시 발표"},
    {"지표": "평균시급 (AHE)", "핵심 정의": "시간당 평균 임금, 전년비(YoY)가 임금발 인플레 압력 판단 기준", "최적 출처": "FRED (CES0500000003)", "수집 방식": "API", "발표 주기": "NFP와 동시 발표"},
    {"지표": "신규실업수당 청구건수", "핵심 정의": "매주 발표되는 초기 실업수당 청구 건수. 고용 냉각을 가장 빨리 포착하는 주간 선행 지표", "최적 출처": "FRED (ICSA)", "수집 방식": "API", "발표 주기": "매주 목요일"},
    {"지표": "ISM 서비스 PMI", "핵심 정의": "50 기준 서비스업 경기 확장/위축 판단. 소비 중심 미국 경제 특성상 중요도 높음", "최적 출처": "ISM 공식 발표 / investing.com 캘린더", "수집 방식": "무료 API 없음 → 수동 입력", "발표 주기": "매월 3영업일경"},
    {"지표": "FOMC (점도표·파월 기자회견)", "핵심 정의": "연준 위원들의 금리 전망 중간값(점도표), 통화정책 방향성의 핵심", "최적 출처": "federalreserve.gov (SEP, 성명서, 기자회견)", "수집 방식": "무료 API 없음 → 수동 입력 + 링크", "발표 주기": "연 8회(점도표는 3·6·9·12월)"},
    {"지표": "한국 경기종합지수 (선행·동행)", "핵심 정의": "순환변동치 기준, 향후 경기 방향(선행)·현재 경기 국면(동행) 판단", "최적 출처": "한국은행 ECOS (통계표 901Y067)", "수집 방식": "API (무료 키)", "발표 주기": "매월"},
    {"지표": "美 2Y·10Y 국채금리 · Fed 정책금리", "핵심 정의": "단기·장기 금리, 스프레드(10Y-2Y)는 대표적 경기침체 예고 지표. 정책금리는 FOMC 결정치", "최적 출처": "FRED (DGS2, DGS10, DFEDTARU)", "수집 방식": "API", "발표 주기": "매 영업일(정책금리는 FOMC 시)"},
    {"지표": "美 국채 수익률곡선", "핵심 정의": "1개월~30년 전 만기 금리를 연결한 곡선. 우하향(역전)되면 경기침체 예고 신호로 흔히 해석", "최적 출처": "FRED (DGS1MO~DGS30)", "수집 방식": "API", "발표 주기": "매 영업일"},
    {"지표": "반도체 버블 지수 (SOX)", "핵심 정의": "PHLX 반도체지수, 닷컴버블 대비 현재 AI 랠리의 과열 정도를 비교", "최적 출처": "Yahoo Finance (^SOX)", "수집 방식": "API(비공식 공개 차트)", "발표 주기": "매 영업일"},
    {"지표": "Shiller PE (CAPE Ratio)", "핵심 정의": "S&P500 10년 평균 실질이익 기준 경기조정 PER. 장기평균(~17) 대비 고평가/저평가 판단", "최적 출처": "multpl.com (Robert Shiller 데이터)", "수집 방식": "무료 API 없음 → 스크래핑", "발표 주기": "매월"},
    {"지표": "버핏지수 근사치", "핵심 정의": "시가총액(S&P500) ÷ GDP, 장기평균=100 지수화. 워런 버핏이 참고하는 밸류에이션 지표 근사치", "최적 출처": "Yahoo Finance(^GSPC) + FRED(GDP)", "수집 방식": "API", "발표 주기": "매 영업일(GDP는 분기)"},
    {"지표": "VIX (공포지수)", "핵심 정의": "S&P500 옵션 내재변동성. 20 이하 안정, 30 이상 공포 국면으로 흔히 해석", "최적 출처": "FRED (VIXCLS)", "수집 방식": "API", "발표 주기": "매 영업일"},
    {"지표": "MOVE Index", "핵심 정의": "ICE BofA MOVE Index. 美 국채 옵션 내재변동성 기준, 채권시장판 VIX", "최적 출처": "Yahoo Finance (^MOVE)", "수집 방식": "API(비공식 공개 차트)", "발표 주기": "매 영업일"},
    {"지표": "KOSPI·KOSDAQ·Nasdaq·Dow", "핵심 정의": "한·미 대표 증시 지수 4종. 시장 탭에서 장중 1시간 단위로 갱신", "최적 출처": "Yahoo Finance (^KS11,^KQ11,^IXIC,^DJI)", "수집 방식": "API(비공식 공개 차트)", "발표 주기": "매 영업일"},
    {"지표": "국내주식 인간지표", "핵심 정의": "국내 주식 커뮤니티(디시인사이드) 게시글 키워드 매칭 기반 긍정/부정 심리 분류", "최적 출처": "디시인사이드 국내주식 갤러리", "수집 방식": "크롤링", "발표 주기": "매일(전일자 기준)"},
    {"지표": "경제 뉴스 Top 10", "핵심 정의": "네이버 뉴스 랭킹 중 경제 키워드가 포함된 전일자 기사", "최적 출처": "네이버 뉴스 랭킹", "수집 방식": "크롤링", "발표 주기": "매일(전일자 기준)"},
]

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_SEEN_FILE = os.path.join(_DATA_DIR, "nav_seen.json")

# 탭별 "새 데이터" 배지의 근거가 되는 원본 파일들. 사용자가 그 탭을 한 번 열어보면
# _mark_seen()이 현재 시각을 기록하고, 그 뒤로는 파일이 그때보다 더 최근에 갱신됐을 때만
# 다시 배지가 뜬다(단순 24시간 타이머가 아니라 "이 갱신을 아직 안 봤는지"를 추적).
FRESH_SOURCES = {
    "human_keyword": ("sentiment_data.json", "sentiment_history.csv"),
    "human_stock": (os.path.join(_DATA_DIR, "latest_run.json"),),
    "multi_notes": ("notes_index.json",),
}


def _load_seen() -> dict:
    if os.path.exists(_SEEN_FILE):
        try:
            with open(_SEEN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_seen(seen: dict) -> None:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen, f)
    except Exception:  # noqa: BLE001
        pass


_SEEN = _load_seen()


def _mark_seen(key: str) -> None:
    _SEEN[key] = datetime.now().timestamp()
    _save_seen(_SEEN)


def _unseen_fresh(key: str, hours: float = 24) -> bool:
    """key에 연결된 원본 파일이 hours시간 이내에 갱신됐고, 사용자가 그 갱신을
    아직 못 봤으면(마지막으로 본 시각보다 파일이 더 최근이면) True."""
    now = datetime.now().timestamp()
    latest = 0.0
    for p in FRESH_SOURCES.get(key, ()):
        if os.path.exists(p):
            latest = max(latest, os.path.getmtime(p))
    if latest == 0.0 or (now - latest) > hours * 3600:
        return False
    return latest > _SEEN.get(key, 0)


def _badge_css(container_key: str, fresh_positions: list[int]) -> str:
    """옵션 목록 중 1부터 시작하는 위치(fresh_positions)에 해당하는 pill 버튼 오른쪽 위에
    작은 빨간 점 배지를 그린다. 라벨 텍스트는 건드리지 않고 CSS만으로 표시한다."""
    if not fresh_positions:
        return ""
    sel = ", ".join(
        f'div[class*="st-key-{container_key}"] div[role="radiogroup"] button:nth-child({i})'
        for i in fresh_positions
    )
    sel_after = ", ".join(
        f'div[class*="st-key-{container_key}"] div[role="radiogroup"] button:nth-child({i})::after'
        for i in fresh_positions
    )
    return f"""
    <style>
    {sel} {{ position: relative; overflow: visible; }}
    {sel_after} {{
        content: "";
        position: absolute;
        top: -3px;
        right: -2px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #FF4B4B;
        border: 2px solid #0F141E;
    }}
    </style>
    """


HUMAN_FRESH = _unseen_fresh("human_keyword") or _unseen_fresh("human_stock")
NOTES_FRESH = _unseen_fresh("multi_notes")

MAIN_SECTIONS = ["종목분석", "경제지표", "인간지표", "멀티차트", "동전점지"]
MAIN_FRESH_FLAGS = [False, False, HUMAN_FRESH, NOTES_FRESH, False]

if "main_section" not in st.session_state:
    st.session_state["main_section"] = "홈"


@st.cache_data
def _b64_file(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


_LOGO_B64 = _b64_file("Dobio_header_logo.png")

# ── 헤더 (Dobio 로고 + 큰 내비게이션, 고정) ───────────────────
with st.container(key="dobio_header"):
    with st.container(key="dobio_header_inner"):
        logo_col, nav_col, menu_col = st.columns([0.16, 0.68, 0.16])
        with logo_col:
            with st.container(key="dobio_home_btn_wrap"):
                st.markdown(
                    f"""
                    <style>
                    div[class*="st-key-dobio_home_btn_wrap"] button {{
                        background-image: url("data:image/png;base64,{_LOGO_B64}");
                        background-repeat: no-repeat;
                        background-position: left center;
                        background-size: contain;
                        width: 132px;
                        height: 34px;
                    }}
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("dobio", key="dobio_home_btn"):
                    st.session_state["main_section"] = "홈"
    with nav_col:
        with st.container(key="mainnav_wrap"):
            st.markdown(
                _badge_css("mainnav_wrap", [i + 1 for i, f in enumerate(MAIN_FRESH_FLAGS) if f]),
                unsafe_allow_html=True,
            )
            _main_sel = st.segmented_control(
                "메인 메뉴", MAIN_SECTIONS,
                default=st.session_state["main_section"] if st.session_state["main_section"] in MAIN_SECTIONS else None,
                label_visibility="collapsed",
            )
        if _main_sel:
            st.session_state["main_section"] = _main_sel
    with menu_col:
        with st.popover("☰", width=980):
            st.caption("거시경제 투자심리 대시보드 · 주식 투자 참고용 초안")
            st.caption("데이터 출처: FRED / ISM / 연준(federalreserve.gov) / ECOS / Yahoo Finance")
            # st.expander 안에 캔버스 기반 st.dataframe을 넣으면, 펼쳐지기 전(0폭) 상태로
            # 마운트된 뒤 폭 재계산이 안 돼 컬럼이 잘려 보이는 버그가 있었다(창 크기를 강제로
            # 바꿔야만 다시 그려짐). st.data_editor(disabled=True)는 같은 파일의 ISM/FOMC
            # 원본 데이터 expander에서 이미 문제 없이 쓰이고 있어 그 패턴을 그대로 재사용한다.
            with st.expander("참고자료1. 지표별 최적 출처 요약", expanded=False):
                st.data_editor(
                    pd.DataFrame(REFERENCE_TABLE_ROWS),
                    width="stretch",
                    height=440,
                    hide_index=True,
                    disabled=True,
                    key="reference_table_1",
                    column_config={
                        "지표": st.column_config.TextColumn(width="medium"),
                        "핵심 정의": st.column_config.TextColumn(width="large"),
                        "최적 출처": st.column_config.TextColumn(width="medium"),
                        "수집 방식": st.column_config.TextColumn(width="medium"),
                        "발표 주기": st.column_config.TextColumn(width="medium"),
                    },
                )

# ── 사이드바 ────────────────────────────────────────────────
with st.sidebar:
    st.header("설정")

    default_fred_key = get_secret("FRED_API_KEY")
    if default_fred_key:
        api_key = default_fred_key
        st.success("FRED API 연결됨")
    else:
        api_key = st.text_input("FRED API Key", type="password")
        st.caption("무료 발급: https://fred.stlouisfed.org/docs/api/api_key.html")

    default_ecos_key = get_secret("ECOS_API_KEY")
    if default_ecos_key:
        ecos_key = default_ecos_key
        st.success("ECOS API 연결됨")
    else:
        ecos_key = st.text_input("ECOS API Key (한국 경기종합지수용)", type="password")
        st.caption("무료 발급: https://ecos.bok.or.kr/api/")

    gemini_key = get_secret("GEMINI_API_KEY")

    start_date = st.date_input("조회 시작일", value=pd.to_datetime("2018-01-01"))
    st.divider()
    st.caption("경제지표는 최대 24시간, 시장 지수는 장중 1시간 단위로 캐시됩니다(API 호출 한도 보호 목적).")

if not api_key:
    st.warning("사이드바에 FRED API Key를 입력해야 자동 지표(물가·고용·금리)를 불러올 수 있습니다.")
    st.stop()


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_series(series_id: str, start: str, key: str) -> pd.DataFrame:
    df = fetch_fred_series(series_id, key, start)
    return add_change_columns(df)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_yahoo_series(symbol: str, start: str, interval: str = "1mo") -> pd.DataFrame:
    return fetch_yahoo_series(symbol, start, interval=interval)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_market_index(symbol: str, start: str, cache_bucket: str) -> pd.DataFrame:
    """시장 탭 실시간 지수용. cache_bucket(market_cache_bucket()의 결과)이 바뀔 때만 재호출된다."""
    return fetch_yahoo_series(symbol, start, interval="1d")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_ecos_series(item_code: str, key: str, start_yyyymm: str, end_yyyymm: str, stat_code: str | None = None) -> pd.DataFrame:
    kwargs = {"stat_code": stat_code} if stat_code else {}
    return fetch_ecos_monthly(item_code, key, start_yyyymm, end_yyyymm, **kwargs)


WORDCLOUD_DIR = os.path.join(os.path.dirname(__file__), "wordclouds")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_news(date_str: str, top_n: int = 10) -> list[dict]:
    return fetch_top_economic_news(date_str, top_n=top_n)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_notes() -> pd.DataFrame:
    return load_notes()


def notes_for_tags(notes_df: pd.DataFrame, tags: list[str]) -> pd.DataFrame:
    """차트에 마커로 얹을 노트만 골라 [date, title, summary] 형태로 정리한다."""
    matched = notes_df[notes_df["tags"].apply(lambda ts: any(t in ts for t in tags))]
    return (
        matched[["note_date", "title", "summary"]]
        .rename(columns={"note_date": "date"})
        .dropna(subset=["date"])
    )


# 종목 심리분석 탭: 배치로 미리 계산된 결과(data/*.json)는 순수 json.load()로만 읽어서 이 탭을
# 열기만 해도 항상 즉시 표시되게 한다. "지금 다시 분석"/"비교분석"/"업종분석" 버튼을 실제로 눌렀을
# 때만 stockanalyzer.{live,analysis.compare,analysis.sector_recommend,crawler.*}를 함수 내부에서
# 지연 import한다 — kiwipiepy(형태소분석)가 이 경로에서 로드되는데, 매 페이지 로드/rerun마다 무조건
# 불러오면 배포 런타임 기동 비용·리스크가 계속 붙으므로 실제 클릭 시점까지 미룬다.
STOCK_GROUP_COLORS = {
    "저평가·수급강세 (추천)": "#2e7d32",
    "저평가·수급약세 (관망)": "#9e9e9e",
    "고평가·수급강세 (주의)": "#f9a825",
    "고평가·수급약세 (비추천)": "#c62828",
}
STOCK_GROUP_EMOJI = {
    "저평가·수급강세 (추천)": "🟢",
    "저평가·수급약세 (관망)": "⚪",
    "고평가·수급강세 (주의)": "🟡",
    "고평가·수급약세 (비추천)": "🔴",
}


def _load_stock_json(filename: str) -> dict | None:
    path = os.path.join(os.path.dirname(__file__), "data", filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_stock_sentiment_data() -> dict | None:
    return _load_stock_json("latest_run.json")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_stock_compare_data() -> dict | None:
    return _load_stock_json("latest_compare.json")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_stock_sector_data() -> dict | None:
    return _load_stock_json("latest_sector.json")


# ── 메인 히어로: 투자심리 게이지 + 종목 검색 ─────────────────
def sentiment_bucket(score: float) -> tuple[str, str]:
    """0~100 심리 점수를 5구간 라벨/색상으로 변환한다(CNN Fear & Greed 스타일)."""
    if score < 20:
        return "극단적 공포", "#D93025"
    if score < 40:
        return "공포", "#F2994A"
    if score < 60:
        return "중립", "#FFD200"
    if score < 80:
        return "탐욕", "#8BC34A"
    return "극단적 탐욕", "#0D6032"


def vix_to_sentiment_score(vix_value: float, low: float = 12.0, high: float = 35.0) -> float:
    """VIX가 낮을수록(안정) 탐욕 쪽, 높을수록(불안) 공포 쪽 점수가 되도록 역변환한다."""
    score = 100 - (vix_value - low) / (high - low) * 100
    return max(0.0, min(100.0, score))


def render_sentiment_gauge(title: str, score: float, source_caption: str):
    bucket_label, bucket_color = sentiment_bucket(score)
    st.markdown(
        f"""
        <div class="dobio-gauge-title">{title}</div>
        <div class="dobio-gauge-track"><div class="dobio-gauge-marker" style="left:{score:.1f}%;"></div></div>
        <div class="dobio-gauge-readout">
            <span class="dobio-gauge-score">{score:.0f}</span>
            <span class="dobio-gauge-bucket" style="background:{bucket_color};">{bucket_label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(source_caption)


if st.session_state["main_section"] == "홈":
    with st.container(key="dobio_herocard"):
        gauge_col1, gauge_col2 = st.columns(2)
        with gauge_col1:
            try:
                sentiment_hist = pd.read_csv("sentiment_history.csv")
                latest_row = sentiment_hist.iloc[-1]
                domestic_score = float(latest_row["positive_pct"])
                domestic_caption = f"국내주식 커뮤니티 여론(긍정 비중) 기준 · {latest_row['date']}"
            except Exception:  # noqa: BLE001
                domestic_score = 50.0
                domestic_caption = "데이터 없음 · 중립(50) 기본값"
            render_sentiment_gauge("🇰🇷 국내 투자심리 (코스피·코스닥)", domestic_score, domestic_caption)
        with gauge_col2:
            try:
                hero_vix_df = get_series("VIXCLS", str(start_date), api_key)
                hero_latest_vix = hero_vix_df.dropna(subset=["value"]).iloc[-1]
                us_score = vix_to_sentiment_score(float(hero_latest_vix["value"]))
                us_caption = f"VIX {hero_latest_vix['value']:.1f} 기준 · {hero_latest_vix['date'].strftime('%Y-%m-%d')}"
            except Exception:  # noqa: BLE001
                us_score = 50.0
                us_caption = "데이터 없음 · 중립(50) 기본값"
            render_sentiment_gauge("🇺🇸 미국 투자심리 (나스닥·다우)", us_score, us_caption)

        st.divider()

        hero_search_col, hero_button_col = st.columns([0.82, 0.18])
        with hero_search_col:
            hero_stock_query = st.text_input(
                "종목 검색", placeholder="분석할 종목명을 입력하세요.",
                label_visibility="collapsed", key="hero_stock_query",
            )
        with hero_button_col:
            hero_search_clicked = st.button("분석하기", type="primary", width="stretch", key="hero_stock_search")
        st.caption("매일 3회 이용할 수 있습니다.")

        if hero_search_clicked and hero_stock_query:
            hero_stock_data = get_stock_sentiment_data()
            hero_match = None
            if hero_stock_data:
                for rec in hero_stock_data.get("recommendations", []):
                    if hero_stock_query.strip() in rec.get("name", ""):
                        hero_match = rec
                        break
            if hero_match:
                st.session_state["main_section"] = "인간지표"
                st.session_state["human_sub"] = "🗣️ 종목 심리분석"
                st.success(f"'{hero_match['name']}' 분석 결과가 있습니다 — 상단 '인간지표' 메뉴에서 확인하세요.")
            else:
                st.info(
                    f"'{hero_stock_query}'는 아직 시가총액 상위 분석 대상에 없습니다. "
                    "'인간지표' 메뉴의 종목 심리분석에서 현재 분석 가능한 상위 종목 목록을 확인해보세요."
                )


def _render_async_job_status(job, prev_key: str, running_label: str, on_first_done=None):
    """4개(파이프라인/비교/업종/전종목목록) 라이브 작업이 공통으로 쓰는 폴링 상태 표시.
    job은 stockanalyzer.jobs의 AsyncJob 인스턴스 — 이 모듈은 kiwipiepy 등 무거운 걸 전혀
    import하지 않으므로, 탭을 열 때마다(버튼을 누르기 전부터) 매 2초 폴링해도 안전하다."""
    status = job.status()
    prev_status = st.session_state.get(prev_key, "idle")
    st.session_state[prev_key] = status["status"]

    if status["status"] == "running":
        st.info(f"🔄 {running_label}")
        for line in status["logs"][-8:]:
            st.caption(line)
    elif status["status"] == "error":
        st.error(f"실패: {status['error']}")
    elif status["status"] == "done" and prev_status == "running":
        if on_first_done:
            on_first_done()
        st.rerun()


@st.fragment(run_every=2)
def render_pipeline_job_status():
    from stockanalyzer.jobs import pipeline_job

    _render_async_job_status(
        pipeline_job, "_pipeline_job_status", "시가총액 상위 10종목 실시간 수집 중...",
        on_first_done=get_stock_sentiment_data.clear,
    )


@st.fragment(run_every=2)
def render_universe_job_status():
    from stockanalyzer.jobs import universe_job

    _render_async_job_status(universe_job, "_universe_job_status", "코스피·코스닥 전 종목 조회 중...")


@st.fragment(run_every=2)
def render_compare_job_status():
    from stockanalyzer.jobs import compare_job

    _render_async_job_status(
        compare_job, "_compare_job_status", "비교분석 중...", on_first_done=get_stock_compare_data.clear
    )


@st.fragment(run_every=2)
def render_sector_job_status():
    from stockanalyzer.jobs import sector_job

    _render_async_job_status(
        sector_job, "_sector_job_status", "업종분석 중...", on_first_done=get_stock_sector_data.clear
    )


# ── 거시경제 캘린더 D-Day 배지 ─────────────────────────────────
# FRED/ISM/FOMC의 실제 발표 캘린더 API를 새로 붙이는 대신(레포 메모의 FRED IP 레이트리밋 이슈를
# 감안해 API 호출을 늘리지 않는 쪽을 택함), REFERENCE_TABLE_ROWS의 '발표 주기' 텍스트에 이미
# 쓰여 있는 규칙(매월 첫째 금요일 등)을 코드로 계산해 근사치 D-day를 보여준다. 공휴일은 반영하지
# 않으므로 실제 발표일과 하루 이틀 어긋날 수 있다.
def _next_weekday_on_or_after(d: datetime, weekday: int) -> datetime:
    """d 이후(포함) 가장 가까운 해당 요일(월=0..일=6)의 날짜."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    """해당 연/월의 n번째 요일(예: 첫째 금요일)."""
    first = datetime(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _nth_business_day_of_month(year: int, month: int, n: int) -> datetime:
    """해당 연/월의 n번째 영업일(주말만 제외한 근사치, 공휴일 미반영)."""
    d = datetime(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _last_business_day_of_month(year: int, month: int) -> datetime:
    d = datetime(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _next_monthly(compute_fn) -> datetime:
    """이번 달 기준 계산일이 이미 지났으면 다음 달로 다시 계산한다."""
    today = datetime.now()
    candidate = compute_fn(today.year, today.month)
    if candidate.date() < today.date():
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        candidate = compute_fn(year, month)
    return candidate


def _dday_badge(target_date: datetime) -> str:
    days = (target_date.date() - datetime.now().date()).days
    if days < 0:
        return ""
    return " `[D-DAY]`" if days == 0 else f" `[D-{days}]`"


RELEASE_SCHEDULES = {
    "nfp_family": lambda: _next_monthly(lambda y, m: _nth_weekday_of_month(y, m, 4, 1)),  # 매월 첫째 금요일
    "jobless_claims": lambda: _next_weekday_on_or_after(datetime.now(), 3),  # 매주 목요일
    "ism_pmi": lambda: _next_monthly(lambda y, m: _nth_business_day_of_month(y, m, 3)),  # 매월 3영업일경
    "core_cpi": lambda: _next_monthly(lambda y, m: _nth_business_day_of_month(y, m, 10)),  # 매월 중순 근사
    "core_pce": lambda: _next_monthly(lambda y, m: _last_business_day_of_month(y, m)),  # 매월 말
}


def release_dday_badge(kind: str) -> str:
    """지표별 발표 주기 규칙 기반 다음 발표일까지 D-day 배지(근사치)."""
    try:
        return _dday_badge(RELEASE_SCHEDULES[kind]())
    except Exception:  # noqa: BLE001
        return ""


def dday_badge_line(kind: str | None = None, fomc: bool = False) -> None:
    """scrollrow 카드에서 제목(h3)과 분리된 고정 높이 줄에 D-day 배지를 그린다. 배지가 없는
    카드도 빈 줄로 동일한 높이를 차지해서, 제목 글자 수 + 배지 유무에 따라 카드마다 제목이
    다른 줄 수로 넘어가 카드 정렬이 깨지는 걸 막는다(제목 글자 크기 고정 트릭과는 별개 문제)."""
    text = (fomc_dday_badge() if fomc else release_dday_badge(kind or "")).replace("`", "").strip()
    st.markdown(f'<div class="dday-badge-line">{text}</div>', unsafe_allow_html=True)


def fomc_dday_badge() -> str:
    """manual_fomc.csv에 사용자가 입력해둔 meeting_date 중 가장 가까운 미래 회의일 기준."""
    try:
        dates = pd.to_datetime(pd.read_csv("manual_fomc.csv")["meeting_date"], errors="coerce").dropna()
        future = dates[dates.dt.date >= datetime.now().date()]
        return _dday_badge(future.min().to_pydatetime()) if not future.empty else ""
    except Exception:  # noqa: BLE001
        return ""


def show_latest_metric(df: pd.DataFrame, col: str, label: str, suffix: str = "%"):
    latest = df.dropna(subset=[col]).iloc[-1]
    prev = df.dropna(subset=[col]).iloc[-2] if len(df.dropna(subset=[col])) > 1 else None
    delta = None if prev is None else round(latest[col] - prev[col], 2)
    st.metric(
        label=f"{label} ({latest['date'].strftime('%Y-%m')})",
        value=f"{latest[col]:.2f}{suffix}",
        delta=f"{delta:+.2f}{suffix}p" if delta is not None else None,
    )


def series_context(df: pd.DataFrame, col: str, label: str, n: int = 6, suffix: str = "", signed: bool = True) -> str:
    """최근 n개 시점을 텍스트로 요약해 AI 해석 프롬프트용 컨텍스트를 만든다."""
    recent = df.dropna(subset=[col]).tail(n)
    fmt = "{:+.2f}" if signed else "{:.2f}"
    lines = [f"{row['date'].strftime('%Y-%m-%d')}: {fmt.format(row[col])}{suffix}" for _, row in recent.iterrows()]
    return f"{label} 최근 추이:\n" + "\n".join(lines)


@st.dialog("지표 해석")
def show_analysis_dialog(title: str, indicator_key: str, name: str, context: str, cache_key: str):
    with st.spinner("해석을 불러오는 중..."):
        analysis = get_indicator_analysis(indicator_key, name, context, cache_key, gemini_key)
    st.subheader(title)
    if analysis is None:
        st.info("GEMINI_API_KEY가 설정되어 있지 않아 해석을 생성할 수 없습니다.")
        return
    if "오류" in analysis:
        st.error(analysis["오류"])
        return
    st.markdown(f"**지표 분석**  \n{analysis.get('지표_분석', '')}")
    st.markdown(f"**거시적 해석**  \n{analysis.get('거시적_해석', '')}")
    st.markdown(f"**정책적 함의**  \n{analysis.get('정책적_함의', '')}")


def analysis_button(indicator_key: str, title: str, context: str, cache_key: str):
    if st.button("🔍 AI 해석", key=f"analysis_{indicator_key}", width="stretch"):
        show_analysis_dialog(title, indicator_key, title, context, cache_key)


# 상단 큰 내비게이션(종목분석/경제지표/인간지표/멀티차트) 아래에 필요한 경우에만
# 세부 메뉴(segmented_control)를 추가로 보여준다. st.tabs()는 화면에 안 보이는 탭이어도
# 매 rerun마다 안의 코드를 전부 실행해서 API 호출이 한 번에 몰리는 문제가 있었기 때문에,
# 선택된 하나의 active_tab 값만 계산해 아래 코드가 실제로 선택된 것만 실행하게 유지한다.
ECON_SUB_LABELS = ["📈 시장", "🐟 물가", "👷 고용", "🏭 경기", "💵 금리", "🏦 연준", "🫧 버블", "📰 뉴스"]
HUMAN_SUB_LABELS = ["🔑 국내주식 키워드", "😨 공포지수", "🔍 종목 검색·비교", "🗣️ 종목 심리분석"]
HUMAN_SEEN_KEYS = {"🔑 국내주식 키워드": "human_keyword", "🗣️ 종목 심리분석": "human_stock"}


def _sub_nav(label: str, session_key: str, options: list[str], seen_keys: dict[str, str] | None = None) -> str:
    """옵션 중 사용자가 아직 못 본 최신 데이터가 있으면 빨간 점 배지를 붙이고,
    현재 선택된(=화면에 보여줄) 옵션은 이 호출 시점에 '봤음'으로 기록한다."""
    seen_keys = seen_keys or {}
    if session_key not in st.session_state:
        st.session_state[session_key] = options[0]
    if st.session_state[session_key] in seen_keys:
        _mark_seen(seen_keys[st.session_state[session_key]])
    wrap_key = f"{session_key}_wrap"
    with st.container(key=wrap_key):
        positions = [
            i + 1 for i, opt in enumerate(options)
            if opt in seen_keys and _unseen_fresh(seen_keys[opt])
        ]
        st.markdown(_badge_css(wrap_key, positions), unsafe_allow_html=True)
        selected = st.segmented_control(
            label, options, default=st.session_state[session_key], label_visibility="collapsed"
        )
    if selected:
        st.session_state[session_key] = selected
    return st.session_state[session_key]


main_section = st.session_state["main_section"]

if main_section == "홈":
    active_tab = None
elif main_section == "멀티차트":
    _mark_seen("multi_notes")
    active_tab = "📓 노트 아카이브"
elif main_section == "동전점지":
    active_tab = "동전점지"
elif main_section == "인간지표":
    active_tab = _sub_nav("인간지표 메뉴", "human_sub", HUMAN_SUB_LABELS, HUMAN_SEEN_KEYS)
elif main_section == "종목분석":
    active_tab = "🏭 업종분석"
else:  # 경제지표
    active_tab = _sub_nav("경제지표 메뉴", "econ_sub", ECON_SUB_LABELS)

# ── 동전점지 ──────────────────────────────────────────────────
# 50:50 고민될 때 캐릭터가 대신 골라주는 재미 기능. 순수 클라이언트 사이드 상호작용(서버에
# 결과를 저장하거나 되돌려받을 필요가 없음)이라 Streamlit 위젯 대신 components.html로
# 자족적인 HTML/CSS/JS 위젯을 그대로 iframe에 심는다. 캐릭터 얼굴은 저작권 문제를 피하려고
# 전부 직접 그린 벡터 일러스트(SVG)이며, 실제 사진 에셋으로 교체할 계획이면 up/down의
# svg 값만 갈아끼우면 된다.
COIN_FLIP_HTML = """
<style>
:root {
  --bg: #0B0F17;
  --card: #131A26;
  --card-line: #23303F;
  --text: #EAEFF5;
  --text-dim: #8B93A3;
  --green: #0D6032;
  --green-bright: #17A863;
  --mint: #BFE8D3;
  --yellow: #FFD200;
  --up: #33C97A;
  --down: #FF7A63;
  --font-display: ui-rounded, "SF Pro Rounded", "Segoe UI", system-ui, sans-serif;
  --font-body: system-ui, -apple-system, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); }
.stage {
  background: radial-gradient(ellipse 620px 360px at 50% -10%, #132A20 0%, var(--bg) 60%);
  color: var(--text);
  font-family: var(--font-body);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem 1.25rem 1.75rem;
}
.card {
  width: 100%;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.25rem;
}
.skins {
  display: flex;
  gap: 8px;
  background: var(--card);
  border: 0.5px solid var(--card-line);
  border-radius: 999px;
  padding: 4px;
}
.skin-btn {
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-dim);
  background: transparent;
  border: none;
  border-radius: 999px;
  padding: 8px 16px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.skin-btn:hover { color: var(--text); }
.skin-btn.active { background: var(--green); color: #EAFBF1; }
.skin-btn:focus-visible { outline: 2px solid var(--yellow); outline-offset: 2px; }
.intro {
  font-size: 14px;
  color: var(--text-dim);
  text-align: center;
  min-height: 20px;
}
.coin-wrap {
  width: 176px;
  height: 176px;
  perspective: 900px;
}
.coin {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  position: relative;
  transform-style: preserve-3d;
  cursor: pointer;
}
.coin.flipping { animation: flip 1.1s cubic-bezier(0.2, 0.7, 0.3, 1) forwards; }
@keyframes flip {
  0% { transform: rotateY(0) translateY(0); }
  45% { transform: rotateY(900deg) translateY(-46px); }
  100% { transform: rotateY(1800deg) translateY(0); }
}
.coin-face {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(155deg, var(--green-bright), var(--green));
  border: 3px solid var(--mint);
  backface-visibility: hidden;
}
.coin-face svg { width: 64%; height: 64%; }
.cta {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 16px;
  color: #000000;
  background: var(--yellow);
  border: none;
  border-radius: 999px;
  padding: 14px 34px;
  cursor: pointer;
  transition: transform 0.12s ease, filter 0.15s ease;
}
.cta:hover { filter: brightness(1.06); }
.cta:active { transform: scale(0.97); }
.cta:disabled { opacity: 0.55; cursor: default; }
.cta:focus-visible { outline: 2px solid var(--mint); outline-offset: 3px; }
.result {
  width: 100%;
  border-radius: 16px;
  padding: 1.1rem 1.25rem;
  text-align: center;
  border: 0.5px solid var(--card-line);
  background: var(--card);
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.result.show { opacity: 1; transform: translateY(0); }
.result.up { background: color-mix(in srgb, var(--up) 14%, var(--card)); border-color: color-mix(in srgb, var(--up) 45%, var(--card-line)); }
.result.down { background: color-mix(in srgb, var(--down) 14%, var(--card)); border-color: color-mix(in srgb, var(--down) 45%, var(--card-line)); }
.verdict {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 20px;
  margin: 0 0 4px;
}
.result.up .verdict { color: var(--up); }
.result.down .verdict { color: var(--down); }
.line { font-size: 14px; color: var(--text-dim); margin: 0; }
.disclaimer {
  font-size: 11.5px;
  color: var(--text-dim);
  text-align: center;
  line-height: 1.6;
  max-width: 320px;
}
@media (prefers-reduced-motion: reduce) {
  .coin.flipping { animation: none; }
}
</style>
<div class="stage">
  <div class="card">
    <div class="skins" role="tablist" aria-label="캐릭터 선택">
      <button class="skin-btn active" data-skin="dobi" role="tab" aria-selected="true">도비</button>
      <button class="skin-btn" data-skin="octopus" role="tab" aria-selected="false">문어 도사</button>
      <button class="skin-btn" data-skin="monkey" role="tab" aria-selected="false">동전 원숭이</button>
    </div>

    <p class="intro" id="intro">도비가 촉을 세우고 있어요.</p>

    <div class="coin-wrap">
      <div class="coin" id="coin">
        <div class="coin-face">
          <svg id="coinSvg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg"></svg>
        </div>
      </div>
    </div>

    <button class="cta" id="askBtn">운명에게 물어보기</button>

    <div class="result" id="result">
      <p class="verdict" id="verdict">&nbsp;</p>
      <p class="line" id="line">&nbsp;</p>
    </div>

    <p class="disclaimer">재미로 보는 동전이에요. 투자 조언이 아니에요 — 최종 판단은 항상 본인의 몫이에요.</p>
  </div>
</div>
<script>
const DOBI_BODY = '<circle cx="50" cy="46" r="30" fill="#EAFBF1"/><path d="M22 46a28 28 0 0 1 56 0v22c0 4-4 6-7 3l-6-6-6 6c-2 2-5 2-7 0l-6-6-6 6c-2 2-5 2-7 0l-6-6-5 5V46z" fill="#EAFBF1"/>';
const MONKEY_BODY = '<circle cx="50" cy="48" r="27" fill="#E3C08C"/><circle cx="27" cy="34" r="9" fill="#E3C08C"/><circle cx="73" cy="34" r="9" fill="#E3C08C"/><ellipse cx="50" cy="53" rx="14" ry="11" fill="#F3DDB8"/>';

const CHARACTERS = {
  dobi: {
    label: "도비",
    intro: "도비가 촉을 세우고 있어요.",
    neutral: DOBI_BODY + '<circle cx="40" cy="44" r="4.2" fill="#0D6032"/><circle cx="61" cy="44" r="4.2" fill="#0D6032"/><circle cx="61" cy="43" r="1.4" fill="#FFD200"/>',
    up: {
      verdict: "가자, GO",
      line: "도비는 이 흐름이 마음에 든대요.",
      svg: DOBI_BODY + '<circle cx="40" cy="43" r="5.4" fill="#0D6032"/><circle cx="61" cy="43" r="5.4" fill="#0D6032"/><circle cx="42" cy="41" r="1.5" fill="#EAFBF1"/><circle cx="63" cy="41" r="1.5" fill="#EAFBF1"/><path d="M32 35 Q37 30 43 33" stroke="#0D6032" stroke-width="2.6" stroke-linecap="round" fill="none"/><path d="M58 33 Q64 30 69 35" stroke="#0D6032" stroke-width="2.6" stroke-linecap="round" fill="none"/><path d="M37 56 Q50 68 64 56" stroke="#0D6032" stroke-width="3.2" stroke-linecap="round" fill="none"/><circle cx="17" cy="30" r="2" fill="#FFD200"/><circle cx="84" cy="32" r="1.6" fill="#FFD200"/><circle cx="50" cy="12" r="1.8" fill="#FFD200"/>',
    },
    down: {
      verdict: "오늘은 패스",
      line: "도비는 오늘 좀 쉬고 싶대요.",
      svg: DOBI_BODY + '<path d="M34 45 Q40 41 46 45" stroke="#0D6032" stroke-width="2.8" stroke-linecap="round" fill="none"/><path d="M55 45 Q61 41 67 45" stroke="#0D6032" stroke-width="2.8" stroke-linecap="round" fill="none"/><path d="M40 60 Q50 52 60 60" stroke="#0D6032" stroke-width="3.2" stroke-linecap="round" fill="none"/><ellipse cx="45" cy="52" rx="1.6" ry="2.6" fill="#6FA8DC"/>',
    },
  },
  octopus: {
    label: "문어 도사",
    intro: "문어 도사가 촉수 여덟 개를 슥 뻗습니다.",
    neutral: '<circle cx="50" cy="40" r="26" fill="#F4D9B8"/><path d="M22 46c-4 8-3 18 2 24m8-20c-3 10 0 20 6 26m10-26c1 11 1 21-2 27m14-27c4 9 5 19 1 26m8-26c6 7 8 16 5 23" stroke="#F4D9B8" stroke-width="6" stroke-linecap="round" fill="none"/><circle cx="41" cy="38" r="4" fill="#0D6032"/><circle cx="59" cy="38" r="4" fill="#0D6032"/>',
    up: {
      verdict: "왼쪽 상자 · 상승",
      line: "이유는 묻지 마세요. 촉수가 그렇다잖아요.",
      svg: '<circle cx="50" cy="40" r="26" fill="#F7C989"/><path d="M20 42c-8 2-13 9-12 18m10-22c-6 6-7 16-1 23m10-24c-2 9 1 18 8 23m12-23c3 9 8 16 15 19m8-23c7 4 12 10 13 18" stroke="#F7C989" stroke-width="6" stroke-linecap="round" fill="none"/><path d="M34 36 Q41 30 48 36" stroke="#0D6032" stroke-width="2.8" stroke-linecap="round" fill="none"/><path d="M52 36 Q59 30 66 36" stroke="#0D6032" stroke-width="2.8" stroke-linecap="round" fill="none"/><path d="M40 50 Q50 57 60 50" stroke="#0D6032" stroke-width="2.6" stroke-linecap="round" fill="none"/><circle cx="50" cy="19" r="2.2" fill="#FFD200"/>',
    },
    down: {
      verdict: "오른쪽 상자 · 하락",
      line: "문어의 촉은 틀린 적이... 가끔 있어요.",
      svg: '<circle cx="50" cy="40" r="26" fill="#C9D3DD"/><path d="M28 52c-2 15-1 27 3 35m13-35c-1 15 1 27 4 35m11-35c1 15 3 27 1 35m14-35c3 14 5 26 2 34" stroke="#C9D3DD" stroke-width="6" stroke-linecap="round" fill="none"/><circle cx="41" cy="40" r="2.6" fill="#5B6673"/><circle cx="59" cy="40" r="2.6" fill="#5B6673"/><path d="M35 33 Q41 36 47 34" stroke="#5B6673" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M53 34 Q59 36 65 33" stroke="#5B6673" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M42 53 Q50 50 58 53" stroke="#5B6673" stroke-width="2.4" stroke-linecap="round" fill="none"/>',
    },
  },
  monkey: {
    label: "동전 원숭이",
    intro: "원숭이가 동전을 하늘 높이 튕깁니다.",
    neutral: MONKEY_BODY + '<circle cx="41" cy="45" r="3.6" fill="#0D6032"/><circle cx="59" cy="45" r="3.6" fill="#0D6032"/>',
    up: {
      verdict: "앞면 · 상승",
      line: "휙- 하고 앞면이 나왔어요!",
      svg: MONKEY_BODY + '<circle cx="41" cy="44" r="4.6" fill="#3B2A1A"/><circle cx="59" cy="44" r="4.6" fill="#3B2A1A"/><circle cx="42.5" cy="42" r="1.3" fill="#fff"/><circle cx="60.5" cy="42" r="1.3" fill="#fff"/><path d="M34 34 Q41 30 47 33" stroke="#6B4A26" stroke-width="2.4" stroke-linecap="round" fill="none"/><path d="M53 33 Q59 30 66 34" stroke="#6B4A26" stroke-width="2.4" stroke-linecap="round" fill="none"/><ellipse cx="50" cy="58" rx="7" ry="6" fill="#6B4A26"/><circle cx="80" cy="24" r="7" fill="#E3C08C"/><rect x="77" y="8" width="6" height="14" rx="3" fill="#E3C08C"/>',
    },
    down: {
      verdict: "뒷면 · 하락",
      line: "휙- 하고 뒷면이 나왔어요!",
      svg: MONKEY_BODY + '<path d="M36 45 L46 43" stroke="#3B2A1A" stroke-width="3" stroke-linecap="round"/><path d="M54 43 L64 45" stroke="#3B2A1A" stroke-width="3" stroke-linecap="round"/><path d="M35 37 L45 40" stroke="#6B4A26" stroke-width="2.6" stroke-linecap="round"/><path d="M55 40 L65 37" stroke="#6B4A26" stroke-width="2.6" stroke-linecap="round"/><path d="M45 60 Q50 58 55 60" stroke="#6B4A26" stroke-width="2.4" stroke-linecap="round" fill="none"/><circle cx="63" cy="60" r="7" fill="#E3C08C"/>',
    },
  },
};

let currentSkin = "dobi";
let flipping = false;

const introEl = document.getElementById("intro");
const coinSvg = document.getElementById("coinSvg");
const coinEl = document.getElementById("coin");
const askBtn = document.getElementById("askBtn");
const resultEl = document.getElementById("result");
const verdictEl = document.getElementById("verdict");
const lineEl = document.getElementById("line");

function paintSkin(id) {
  const c = CHARACTERS[id];
  coinSvg.innerHTML = c.neutral;
  introEl.textContent = c.intro;
}
paintSkin(currentSkin);

document.querySelectorAll(".skin-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (flipping) return;
    document.querySelectorAll(".skin-btn").forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    currentSkin = btn.dataset.skin;
    paintSkin(currentSkin);
    resultEl.classList.remove("show", "up", "down");
  });
});

function flip() {
  if (flipping) return;
  flipping = true;
  askBtn.disabled = true;
  resultEl.classList.remove("show", "up", "down");
  coinEl.classList.remove("flipping");
  void coinEl.offsetWidth;
  coinEl.classList.add("flipping");

  const isUp = Math.random() < 0.5;
  let finished = false;
  const done = () => {
    if (finished) return;
    finished = true;
    coinEl.classList.remove("flipping");
    const c = CHARACTERS[currentSkin];
    const outcome = isUp ? c.up : c.down;
    coinSvg.innerHTML = outcome.svg;
    verdictEl.textContent = outcome.verdict;
    lineEl.textContent = outcome.line;
    resultEl.classList.add("show", isUp ? "up" : "down");
    flipping = false;
    askBtn.disabled = false;
  };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    setTimeout(done, 150);
  } else {
    // animationend는 탭이 백그라운드거나 일부 브라우저 환경에서 안 붙는 경우가 있어,
    // 애니메이션 길이(1.1s)보다 살짝 긴 타이머를 안전망으로 같이 걸어둔다.
    coinEl.addEventListener("animationend", done, { once: true });
    setTimeout(done, 1300);
  }
}

askBtn.addEventListener("click", flip);
coinEl.addEventListener("click", flip);
</script>
"""

if active_tab == "동전점지":
    st.subheader("동전점지")
    st.caption(
        "50:50으로 고민될 때, 캐릭터에게 대신 골라달라고 해보세요. "
        "재미로 보는 기능이며 투자 조언이 아닙니다."
    )
    components.html(COIN_FLIP_HTML, height=620, scrolling=False)

# ── 시장 ────────────────────────────────────────────────────
if active_tab == "📈 시장":
    with st.container(key="scrollrow_market"):
        c1, c2, c3, c4 = st.columns(4)

        market_indices = [
            (c1, "^KS11", "KOSPI", "한국 대표 증시 지수. 국내 대형주 중심.", "https://m.stock.naver.com/domestic/index/KOSPI/discussion"),
            (c2, "^KQ11", "KOSDAQ", "한국 성장·중소형주 중심 지수. 코스피 대비 변동성이 큼.", "https://m.stock.naver.com/domestic/index/KOSDAQ/discussion"),
            (c3, "^IXIC", "NASDAQ", "미국 기술주 중심 지수. 성장주·금리 민감도가 높음.", "https://m.stock.naver.com/worldstock/index/.IXIC/discussion"),
            (c4, "^DJI", "Dow Jones", "미국 대형 우량주 30종목 지수. 경기민감·전통산업 비중이 큼.", "https://m.stock.naver.com/worldstock/index/.DJI/discussion"),
        ]
        for col, symbol, name, desc, discussion_url in market_indices:
            with col:
                st.subheader(name)
                st.caption(desc)
                try:
                    tz_name, open_time, close_time = MARKET_HOURS[symbol]
                    bucket = market_cache_bucket(tz_name, open_time, close_time)
                    df = get_market_index(symbol, str(start_date), bucket)
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    chg_pct = (latest["close"] - prev["close"]) / prev["close"] * 100
                    mc1, mc2 = st.columns([3, 1])
                    with mc1:
                        st.metric(
                            f"최근 종가 ({latest['date'].strftime('%Y-%m-%d')})",
                            f"{latest['close']:,.2f}",
                            delta=f"{chg_pct:+.2f}%",
                        )
                    if discussion_url:
                        with mc2:
                            st.link_button("🔥 Hot 토픽", discussion_url, width="stretch")
                    render_zoomable_chart(df, x="date", y="close", y_title="종가", key=f"market_{symbol}")
                except Exception as e:  # noqa: BLE001
                    st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 물가 ────────────────────────────────────────────────────
if active_tab == "🐟 물가":
    with st.container(key="scrollrow_inflation"):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.subheader("Core CPI (MoM)")
            dday_badge_line("core_cpi")
            st.caption("에너지·식품을 제외한 소비자물가지수의 전월 대비 변화율. 연준의 근원 인플레이션 판단 지표.")
            cpi_latest_date = None
            try:
                df = get_series("CPILFESL", str(start_date), api_key)
                cpi_latest_date = df.dropna(subset=["MoM%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    show_latest_metric(df, "MoM%", "최근 발표 MoM")
                with mc2:
                    analysis_button(
                        "cpi", "Core CPI (MoM)", series_context(df, "MoM%", "Core CPI MoM", suffix="%"), cpi_latest_date
                    )
                render_zoomable_chart(
                    df, x="date", y="MoM%", y_title="MoM (%)", rule_y=0.2, rule_label="연준 목표", key="cpi"
                )
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c2:
            st.subheader("Core PCE (MoM)")
            dday_badge_line("core_pce")
            st.caption("에너지·식품을 제외한 개인소비지출 물가지수 전월비. 연준이 공식 목표(2%)로 삼는 지표.")
            try:
                df = get_series("PCEPILFE", str(start_date), api_key)
                pce_latest_date = df.dropna(subset=["MoM%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    show_latest_metric(df, "MoM%", "최근 발표 MoM")
                with mc2:
                    analysis_button(
                        "pce", "Core PCE (MoM)", series_context(df, "MoM%", "Core PCE MoM", suffix="%"), pce_latest_date
                    )
                render_zoomable_chart(df, x="date", y="MoM%", y_title="MoM (%)", key="pce")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c3:
            st.subheader("WTI 유가")
            dday_badge_line()
            st.caption("서부텍사스산 원유 현물가($/배럴). 에너지 인플레이션과 에너지주 실적에 직결되는 선행 변수.")
            try:
                df = get_series("DCOILWTICO", str(start_date), api_key)
                latest = df.dropna(subset=["value"]).iloc[-1]
                prev = df.dropna(subset=["value"]).iloc[-2]
                # 가격 자체는 매일 갱신되지만, 해석은 주 1회(ISO 주차 기준)만 새로 생성한다.
                iso = latest["date"].isocalendar()
                wti_week_key = f"{iso.year}-W{iso.week:02d}"
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    st.metric(
                        f"최근 종가 ({latest['date'].strftime('%Y-%m-%d')})",
                        f"${latest['value']:.2f}",
                        delta=f"{latest['value'] - prev['value']:+.2f}",
                    )
                with mc2:
                    analysis_button(
                        "wti", "WTI 유가", series_context(df, "value", "WTI 현물가", suffix="$", signed=False), wti_week_key
                    )
                render_zoomable_chart(df, x="date", y="value", y_title="$/배럴", key="wti")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c4:
            st.subheader("기대인플레이션 (BEI)")
            dday_badge_line()
            st.caption("국채-물가연동국채(TIPS) 스프레드로 산출한 시장 기대인플레이션. 5년물·10년물 비교.")
            try:
                df5 = get_series("T5YIE", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "5년 기대인플레이션"})
                df10y = get_series("T10YIE", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "10년 기대인플레이션"})
                bei_merged = pd.merge(df5, df10y, on="date", how="inner")
                latest = bei_merged.iloc[-1]
                # 기대인플레이션은 매일 갱신되는 시장 데이터지만, 해석은 CPI가 새로 발표될 때에 맞춰
                # 한 달에 한 번만 CPI/PCE와 같이 갱신한다(요청 사양).
                bei_context = (
                    series_context(bei_merged.rename(columns={"5년 기대인플레이션": "value"}), "value", "5년 기대인플레이션", suffix="%", signed=False)
                    + "\n"
                    + series_context(bei_merged.rename(columns={"10년 기대인플레이션": "value"}), "value", "10년 기대인플레이션", suffix="%", signed=False)
                )
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    st.metric(f"5년 BEI ({latest['date'].strftime('%Y-%m-%d')})", f"{latest['5년 기대인플레이션']:.2f}%")
                with mc2:
                    if cpi_latest_date:
                        analysis_button("bei", "기대인플레이션 (BEI)", bei_context, cpi_latest_date)
                bei_long = bei_merged.melt(id_vars="date", var_name="구분", value_name="값")
                render_zoomable_chart(
                    bei_long,
                    x="date",
                    y="값",
                    color="구분",
                    color_domain=["5년 기대인플레이션", "10년 기대인플레이션"],
                    color_range=["#4C78A8", "#F58518"],
                    y_title="%",
                    key="bei",
                )
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 고용 ────────────────────────────────────────────────────
if active_tab == "👷 고용":
    with st.container(key="scrollrow_labor"):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.subheader("비농업 고용")
            dday_badge_line("nfp_family")
            st.caption("비농업 부문 신규 고용자 수(전월 대비 증감, 천 명). 경기 모멘텀의 대표 선행 신호.")
            try:
                df = get_series("PAYEMS", str(start_date), api_key)
                payrolls_latest_date = df.dropna(subset=["MoM_chg"]).iloc[-1]["date"].strftime("%Y-%m-%d")
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    show_latest_metric(df, "MoM_chg", "전월 대비 증감", suffix="K")
                with mc2:
                    analysis_button(
                        "payrolls",
                        "비농업 고용 (Nonfarm Payrolls)",
                        series_context(df, "MoM_chg", "비농업 고용 전월 대비 증감(천 명)", suffix="K"),
                        payrolls_latest_date,
                    )
                render_zoomable_chart(df, x="date", y="MoM_chg", y_title="천 명", mark="bar", key="payrolls")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c2:
            st.subheader("실업률")
            dday_badge_line("nfp_family")
            st.caption("경제활동인구 중 실업자 비율. 연준 이중책무(물가·고용) 중 고용 측면 판단 근거.")
            try:
                df = get_series("UNRATE", str(start_date), api_key)
                unrate_latest_date = df.dropna(subset=["value"]).iloc[-1]["date"].strftime("%Y-%m-%d")
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    show_latest_metric(df, "value", "최근 실업률")
                with mc2:
                    analysis_button(
                        "unrate", "실업률", series_context(df, "value", "실업률(%)", suffix="%", signed=False), unrate_latest_date
                    )
                render_zoomable_chart(df, x="date", y="value", y_title="%", key="unrate")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c3:
            st.subheader("평균시급 (YoY)")
            dday_badge_line("nfp_family")
            st.caption("시간당 평균 임금 전년 대비 상승률. 임금발 인플레이션 압력을 가늠하는 지표.")
            try:
                df = get_series("CES0500000003", str(start_date), api_key)
                wages_latest_date = df.dropna(subset=["YoY%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    show_latest_metric(df, "YoY%", "최근 발표 YoY")
                with mc2:
                    analysis_button(
                        "wages", "평균시급 (YoY)", series_context(df, "YoY%", "평균시급 YoY", suffix="%"), wages_latest_date
                    )
                render_zoomable_chart(df, x="date", y="YoY%", y_title="YoY (%)", key="wages")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

        with c4:
            st.subheader("신규실업수당 청구건수")
            dday_badge_line("jobless_claims")
            st.caption("매주 발표되는 초기 실업수당 청구 건수. 고용 냉각을 가장 빨리 포착하는 주간 선행 지표.")
            try:
                df = get_series("ICSA", str(start_date), api_key)
                latest = df.dropna(subset=["value"]).iloc[-1]
                prev = df.dropna(subset=["value"]).iloc[-2]
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    st.metric(
                        f"최근 발표 ({latest['date'].strftime('%Y-%m-%d')})",
                        f"{latest['value']:,.0f}건",
                        delta=f"{latest['value'] - prev['value']:+,.0f}",
                    )
                with mc2:
                    analysis_button(
                        "claims",
                        "신규실업수당 청구건수",
                        series_context(df, "value", "신규실업수당 청구건수", signed=False),
                        latest["date"].strftime("%Y-%m-%d"),
                    )
                render_zoomable_chart(df, x="date", y="value", y_title="건", key="claims")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 경기·연준 (한국 경기종합지수 + 수동 입력 지표) ──────────
if active_tab == "🏭 경기":
    st.subheader("한국 경기종합지수 (선행·동행 순환변동치)")
    st.caption(
        "선행지수순환변동치는 향후 경기 방향, 동행지수순환변동치는 현재 경기 국면을 보여줍니다. "
        "100을 기준으로 위/아래가 경기 확장/수축 국면을 의미합니다. 출처: 한국은행 ECOS (통계표 901Y067)."
    )
    if not ecos_key:
        st.info("사이드바에 ECOS API Key를 입력하면 자동으로 표시됩니다. 무료 발급: https://ecos.bok.or.kr/api/")
    else:
        try:
            start_ym = pd.to_datetime(start_date).strftime("%Y%m")
            end_ym = pd.Timestamp.today().strftime("%Y%m")
            leading = get_ecos_series(LEADING_INDEX_ITEM, ecos_key, start_ym, end_ym).rename(
                columns={"value": "선행종합지수(순환변동치)"}
            )
            coincident = get_ecos_series(COINCIDENT_INDEX_ITEM, ecos_key, start_ym, end_ym).rename(
                columns={"value": "동행종합지수(순환변동치)"}
            )
            merged_kr = pd.merge(leading, coincident, on="date", how="inner")
            long_kr = merged_kr.melt(id_vars="date", var_name="구분", value_name="값")
            render_zoomable_chart(
                long_kr,
                x="date",
                y="값",
                color="구분",
                color_domain=["선행종합지수(순환변동치)", "동행종합지수(순환변동치)"],
                color_range=["#F58518", "#4C78A8"],
                y_title="지수(2020=100)",
                key="kr_index",
            )
        except Exception as e:  # noqa: BLE001
            st.warning(f"데이터를 불러올 수 없습니다: {e}")

    st.divider()

    st.subheader("ISM 서비스 PMI" + release_dday_badge("ism_pmi"))
    st.caption(
        "50을 기준으로 서비스업 경기 확장(>50)/위축(<50)을 판단. "
        "소비 중심인 미국 경제 특성상 주가 방향성에 영향이 큰 지표. "
        "저작권 이슈로 무료 API가 없어 매월 발표 후 직접 입력이 필요합니다."
    )
    st.markdown("발표 확인처: [ISM 공식 발표](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/services/) · [investing.com 캘린더](https://www.investing.com/economic-calendar/ism-non-manufacturing-pmi-176)")

    ism_path = "manual_ism_pmi.csv"
    ism_df = pd.read_csv(ism_path)
    with st.expander("📋 원본 데이터 보기 / 편집 (클릭하여 펼치기)", expanded=False):
        ism_edited = st.data_editor(ism_df, num_rows="dynamic", key="ism_editor", width="stretch")
        if st.button("ISM PMI 저장"):
            ism_edited.to_csv(ism_path, index=False)
            st.success("저장되었습니다.")

    if not ism_edited.dropna(subset=["release_date", "pmi"]).empty:
        chart_df = ism_edited.dropna(subset=["release_date", "pmi"]).copy()
        chart_df["release_date"] = pd.to_datetime(chart_df["release_date"])
        chart_df = chart_df[chart_df["release_date"] >= pd.to_datetime(start_date)]
        render_zoomable_chart(
            chart_df, x="release_date", y="pmi", y_title="PMI", rule_y=50, rule_label="기준선(50)", key="ism_pmi"
        )
    else:
        st.info("위 표에 발표일(release_date)·기간(period)·수치(pmi)를 입력하면 추세 차트가 표시됩니다.")

if active_tab == "🏦 연준":
    st.subheader("FOMC (점도표 · 파월 기자회견)" + fomc_dday_badge())
    st.caption(
        "연준 위원들의 향후 금리 전망 중간값(점도표)과 성명서·기자회견. "
        "점도표는 연 4회(3·6·9·12월) SEP 발표 시 공개되며, 시각 자료라 API가 없어 수동 입력이 필요합니다."
    )
    st.markdown(
        "발표 확인처: [FOMC 일정·성명서](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · "
        "[SEP(점도표) 자료](https://www.federalreserve.gov/monetarypolicy/fomcprojtabl.htm) · "
        "[파월 기자회견 영상](https://www.federalreserve.gov/monetarypolicy/fomcpresconf.htm)"
    )

    fomc_path = "manual_fomc.csv"
    fomc_df = pd.read_csv(fomc_path)
    with st.expander("📋 원본 데이터 보기 / 편집 (클릭하여 펼치기)", expanded=False):
        fomc_edited = st.data_editor(fomc_df, num_rows="dynamic", key="fomc_editor", width="stretch")
        if st.button("FOMC 데이터 저장"):
            fomc_edited.to_csv(fomc_path, index=False)
            st.success("저장되었습니다.")

    if not fomc_edited.dropna(subset=["meeting_date"]).empty:
        chart_df = fomc_edited.dropna(subset=["meeting_date"]).copy()
        chart_df["meeting_date"] = pd.to_datetime(chart_df["meeting_date"])
        cols = [c for c in ["fed_funds_upper", "dot_current_year", "dot_next_year", "dot_longer_run"] if c in chart_df]
        long_df = chart_df.melt(id_vars="meeting_date", value_vars=cols, var_name="구분", value_name="값").dropna(
            subset=["값"]
        )
        render_zoomable_chart(long_df, x="meeting_date", y="값", color="구분", y_title="금리(%)", key="fomc")
    else:
        st.info("위 표에 회의일(meeting_date)과 금리·점도표 값을 입력하면 추세 차트가 표시됩니다.")

# ── 금리 ────────────────────────────────────────────────────
if active_tab == "💵 금리":
    st.subheader("美 2년물·10년물 국채금리 & 연준 정책금리")
    st.caption(
        "단기(2Y)·장기(10Y) 국채금리와 연준 정책금리(상단, 빨간선), 한국은행 기준금리(진한 파란선). "
        "10Y-2Y 스프레드가 역전(음수)되면 대표적인 경기침체 예고 신호로 해석됩니다."
    )

    try:
        df2 = get_series("DGS2", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "2Y"})
        df10 = get_series("DGS10", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "10Y"})
        dff = get_series("DFEDTARU", str(start_date), api_key)[["date", "value"]].rename(
            columns={"value": "Fed 정책금리(상단)"}
        )
        merged = pd.merge(df2, df10, on="date", how="inner")
        merged["10Y-2Y 스프레드"] = merged["10Y"] - merged["2Y"]
        merged = pd.merge(merged, dff, on="date", how="left")
        merged["Fed 정책금리(상단)"] = merged["Fed 정책금리(상단)"].ffill()

        rate_cols = ["2Y", "10Y", "Fed 정책금리(상단)"]
        rate_colors = ["#4C78A8", "#54A24B", "#E45756"]
        if ecos_key:
            start_ym = pd.to_datetime(start_date).strftime("%Y%m")
            end_ym = pd.Timestamp.today().strftime("%Y%m")
            kr_base = get_ecos_series(BASE_RATE_ITEM, ecos_key, start_ym, end_ym, stat_code=BASE_RATE_STAT_CODE)[
                ["date", "value"]
            ].rename(columns={"value": "한국은행 기준금리"}).sort_values("date")
            # ECOS는 월별(그 달 1일자로 스탬프) 값이라, 미국 거래일 기준인 merged와 날짜가
            # 정확히 일치하는 경우만 값이 들어가던 기존 merge+ffill 방식은 1일이 주말/공휴일이면
            # 그 달의 갱신값이 통째로 누락됐다(예: 금리가 인상돼도 화면에 반영 안 되는 원인).
            # merge_asof(backward)로 "그 시점 기준 가장 최근 발표값"을 항상 채우도록 고친다.
            merged = pd.merge_asof(merged.sort_values("date"), kr_base, on="date", direction="backward")
            rate_cols.append("한국은행 기준금리")
            rate_colors.append("#08306B")  # 진한 파란색
        else:
            st.caption("사이드바에 ECOS API Key를 입력하면 한국은행 기준금리도 함께 표시됩니다.")

        latest = merged.iloc[-1]
        prev = merged.iloc[-2]
        latest_date = latest["date"].strftime("%Y-%m-%d")

        fed_valid = dff.dropna(subset=["Fed 정책금리(상단)"])
        fed_latest_date = fed_valid["date"].iloc[-1].strftime("%Y-%m-%d") if len(fed_valid) else None

        row1 = st.columns(3)
        for (label, col), c in zip([("2년물", "2Y"), ("10년물", "10Y")], row1):
            with c:
                delta_abs = latest[col] - prev[col]
                delta_pct = delta_abs / prev[col] * 100 if prev[col] else 0.0
                st.metric(
                    f"{label} ({latest_date})",
                    f"{latest[col]:.2f}%",
                    delta=f"{delta_abs:+.3f}%p ({delta_pct:+.2f}%)",
                )
        with row1[2]:
            spread = latest["10Y-2Y 스프레드"]
            st.metric("10Y-2Y 스프레드", f"{spread:+.2f}%p", delta="역전 중" if spread < 0 else "정상")

        row2 = st.columns(3)
        with row2[0]:
            fed_label = f"Fed 정책금리(상단) ({fed_latest_date})" if fed_latest_date else "Fed 정책금리(상단)"
            st.metric(fed_label, f"{latest['Fed 정책금리(상단)']:.2f}%")
        if "한국은행 기준금리" in merged and pd.notna(latest["한국은행 기준금리"]):
            with row2[1]:
                bok_valid = kr_base.dropna(subset=["한국은행 기준금리"])
                bok_latest_date = bok_valid["date"].iloc[-1].strftime("%Y-%m-%d") if len(bok_valid) else None
                bok_label = f"한국은행 기준금리 ({bok_latest_date})" if bok_latest_date else "한국은행 기준금리"
                st.metric(bok_label, f"{latest['한국은행 기준금리']:.2f}%")

        long_rates = merged.melt(
            id_vars="date", value_vars=rate_cols, var_name="구분", value_name="금리(%)"
        ).dropna(subset=["금리(%)"])
        render_zoomable_chart(
            long_rates,
            x="date",
            y="금리(%)",
            color="구분",
            color_domain=rate_cols,
            color_range=rate_colors,
            y_title="금리(%)",
            key="rates_curve",
        )
        st.markdown("**장단기금리차 (10Y-2Y 스프레드)**")
        render_zoomable_chart(
            merged, x="date", y="10Y-2Y 스프레드", y_title="%p", rule_y=0, rule_label="역전 기준선(0)",
            key="rates_spread",
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"데이터를 불러올 수 없습니다: {e}")

    st.divider()

    st.subheader("美 국채 수익률곡선 (Yield Curve)")
    st.caption(
        "만기별 국채금리를 연결한 곡선. 단기금리가 장기금리보다 높아 우하향(역전)되면 "
        "경기침체를 앞두고 흔히 나타나는 신호로 해석됩니다. 1년 전과 비교해 곡선 형태 변화를 볼 수 있습니다."
    )

    YIELD_MATURITIES = [
        ("1M", "DGS1MO"),
        ("3M", "DGS3MO"),
        ("6M", "DGS6MO"),
        ("1Y", "DGS1"),
        ("2Y", "DGS2"),
        ("3Y", "DGS3"),
        ("5Y", "DGS5"),
        ("7Y", "DGS7"),
        ("10Y", "DGS10"),
        ("20Y", "DGS20"),
        ("30Y", "DGS30"),
    ]
    # DGS2/DGS10은 이 탭 위쪽에서 이미 str(start_date)로 조회했으므로, 같은 인자로 호출해
    # get_series 캐시를 재사용한다(중복 FRED 호출 방지). 나머지 9개는 곡선에 필요한 최근
    # 1년치만 있으면 되므로, 사이드바 시작일(보통 2018~)까지 통째로 당겨오지 않고 짧은
    # 창으로 제한해 메모리 사용량을 늘리지 않는다.
    yield_start = (pd.Timestamp.today() - pd.Timedelta(days=450)).strftime("%Y-%m-%d")
    one_year_ago = pd.Timestamp.today() - pd.Timedelta(days=365)

    curve_rows = []
    latest_curve_date = None
    yield_curve_error = None
    for label, series_id in YIELD_MATURITIES:
        fetch_start = str(start_date) if series_id in ("DGS2", "DGS10") else yield_start
        try:
            s = get_series(series_id, fetch_start, api_key).dropna(subset=["value"])
        except Exception as e:  # noqa: BLE001
            yield_curve_error = e
            continue
        if s.empty:
            continue
        latest_row = s.iloc[-1]
        if latest_curve_date is None:
            latest_curve_date = latest_row["date"]
        curve_rows.append({"만기": label, "금리(%)": latest_row["value"], "구분": "현재"})
        past = s[s["date"] <= one_year_ago]
        if not past.empty:
            curve_rows.append({"만기": label, "금리(%)": past.iloc[-1]["value"], "구분": "1년 전"})

    if curve_rows:
        curve_df = pd.DataFrame(curve_rows)
        maturity_order = [m[0] for m in YIELD_MATURITIES]
        st.caption(f"기준일: {latest_curve_date.strftime('%Y-%m-%d')} (현재) vs 1년 전")
        st.altair_chart(
            zoom_chart(
                curve_df,
                x="만기",
                y="금리(%)",
                color="구분",
                color_domain=["현재", "1년 전"],
                color_range=["#E45756", "#B0B0B0"],
                y_title="금리(%)",
                x_type="O",
                x_sort=maturity_order,
            ),
            width="stretch",
        )
        if yield_curve_error:
            st.caption(f"⚠️ 일부 만기는 불러오지 못해 곡선에서 제외됐습니다: {yield_curve_error}")
    else:
        st.info("수익률곡선 데이터를 불러오지 못했습니다.")

# ── 버블 ────────────────────────────────────────────────────
if active_tab == "🫧 버블":
    st.subheader("반도체 버블 지수 (닷컴버블 vs AI·반도체 랠리)")
    st.caption(
        "PHLX 반도체지수(SOX)를 각 랠리 시작월 = 100으로 지수화해 상승폭을 직접 비교합니다. "
        "닷컴버블(1995~2002)과 현재 AI·반도체 랠리(2019~)의 궤적을 겹쳐서 과열 정도를 가늠해볼 수 있습니다."
    )
    try:
        sox = get_yahoo_series("^SOX", "1994-01-01")

        def indexed_window(df: pd.DataFrame, start: str, months: int, label: str) -> pd.DataFrame:
            window = df[df["date"] >= pd.to_datetime(start)].head(months).copy()
            if window.empty:
                return window
            window["months_since_start"] = range(len(window))
            window["지수화(시작월=100)"] = window["close"] / window["close"].iloc[0] * 100
            window["구간"] = label
            return window

        dotcom = indexed_window(sox, "1995-01-01", 96, "닷컴버블(1995~2002)")
        current_rally = indexed_window(sox, "2019-01-01", 96, "AI·반도체 랠리(2019~)")
        combo = pd.concat([dotcom, current_rally], ignore_index=True)

        st.altair_chart(
            zoom_chart(
                combo,
                x="months_since_start",
                y="지수화(시작월=100)",
                color="구간",
                color_domain=["닷컴버블(1995~2002)", "AI·반도체 랠리(2019~)"],
                color_range=["#B279A2", "#E45756"],
                y_title="지수화(시작월=100)",
                x_type="Q",
            ),
            width="stretch",
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"데이터를 불러올 수 없습니다: {e}")

    st.divider()

    st.subheader("Shiller PE (CAPE Ratio)")
    st.caption(
        "경기조정주가수익비율(S&P500 10년 평균 실질이익 기준). 장기 평균(약 17)보다 높을수록 역사적으로 고평가 구간. "
        "출처: multpl.com (Robert Shiller 데이터 기반)."
    )
    try:
        shiller_df = pd.read_csv("manual_shiller_pe.csv", parse_dates=["date"])
        shiller_df = shiller_df[shiller_df["date"] >= pd.to_datetime(start_date)]
        latest = shiller_df.dropna(subset=["shiller_pe"]).iloc[-1]
        st.metric("최근 Shiller PE", f"{latest['shiller_pe']:.1f}", help=f"기준월: {latest['date'].strftime('%Y-%m')}")

        render_zoomable_chart(
            shiller_df, x="date", y="shiller_pe", y_title="Shiller PE", rule_y=17, rule_label="장기평균(~17)", key="shiller_pe"
        )
    except FileNotFoundError:
        st.info("manual_shiller_pe.csv 파일을 찾을 수 없습니다.")

    st.divider()

    st.subheader("버핏지수 근사치 (S&P500 / GDP, 장기평균=100 지수화)")
    st.caption(
        "워런 버핏이 참고하는 '시가총액 ÷ GDP' 밸류에이션 지표의 근사치입니다. "
        "FRED에서 Wilshire5000 시가총액 지수가 단종되어 S&P500으로 대체 산출했으며, "
        "절대 수치가 아닌 자체 장기평균 대비 상대적 고평가/저평가 판단용으로만 참고하세요."
    )
    try:
        sp500 = get_yahoo_series("^GSPC", "1985-01-01")
        gdp = get_series("GDP", "1985-01-01", api_key)[["date", "value"]].rename(columns={"value": "gdp"})
        gdp_monthly = gdp.set_index("date").resample("MS").ffill().reset_index()
        buffett = pd.merge_asof(sp500.sort_values("date"), gdp_monthly.sort_values("date"), on="date", direction="backward")
        buffett = buffett.dropna(subset=["gdp"])
        buffett["ratio"] = buffett["close"] / buffett["gdp"]
        buffett["지수화"] = buffett["ratio"] / buffett["ratio"].mean() * 100
        buffett_view = buffett[buffett["date"] >= pd.to_datetime(start_date)]
        if not buffett_view.empty:
            st.metric("최근 버핏지수(장기평균=100)", f"{buffett_view.iloc[-1]['지수화']:.0f}")
            render_zoomable_chart(buffett_view, x="date", y="지수화", y_title="버핏지수(장기평균=100)", key="buffett")
    except Exception as e:  # noqa: BLE001
        st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 인간지표 (시장 심리) ──────────────────────────────────────
if active_tab == "🔑 국내주식 키워드":
    st.subheader("국내주식 인간지표")
    st.caption(
        "국내 주식 커뮤니티의 전날 게시글을 시간대 4구간으로 나눠, "
        "키워드 사전 기반으로 긍정/부정을 분류하고 구간별 점유율을 보여줍니다. "
        "AI 감성분석이 아닌 단순 키워드 매칭 휴리스틱이므로 참고용으로만 활용하세요."
    )

    try:
        with open("sentiment_data.json", encoding="utf-8") as f:
            sentiment_data = json.load(f)
    except FileNotFoundError:
        sentiment_data = None

    if sentiment_data is None:
        st.info(
            "아직 수집된 데이터가 없습니다. `python sentiment_scraper.py` 를 실행하면 "
            "`sentiment_data.json`이 생성되어 자동으로 표시됩니다."
        )
    else:
        st.caption(
            f"대상일: {sentiment_data['target_date']} (KST 09:00 ~ 익일 06:00) · "
            f"생성 시각: {sentiment_data['generated_at'][:16].replace('T', ' ')}"
        )

        day_total = sentiment_data.get("total", {"positive_posts": 0, "negative_posts": 0})
        day_pos = day_total["positive_posts"]
        day_neg = day_total["negative_posts"]
        day_classified = day_pos + day_neg
        day_pos_pct = day_pos / day_classified * 100 if day_classified else 0.0
        day_neg_pct = day_neg / day_classified * 100 if day_classified else 0.0
        st.caption(
            f"수집 게시글 {sentiment_data['total_posts_scanned']:,}건, "
            f"긍정 분류 {day_pos}건({day_pos_pct:.2f}%), "
            f"부정 분류 {day_neg}건({day_neg_pct:.2f}%)"
        )

        bucket_labels = list(sentiment_data["buckets"].keys())
        bucket_tabs = st.tabs(bucket_labels)
        for i, (label, bucket_tab) in enumerate(zip(bucket_labels, bucket_tabs)):
            bucket = sentiment_data["buckets"][label]
            with bucket_tab:
                classified = bucket["positive_posts"] + bucket["negative_posts"]
                pos_pct = bucket["positive_posts"] / classified * 100 if classified else 0.0
                neg_pct = bucket["negative_posts"] / classified * 100 if classified else 0.0
                st.caption(
                    f"수집 게시글 {bucket['total_posts']:,}건 · "
                    f"긍정 분류 {bucket['positive_posts']}건({pos_pct:.2f}%) · "
                    f"부정 분류 {bucket['negative_posts']}건({neg_pct:.2f}%)"
                )
                kc1, kc2 = st.columns(2)
                with kc1:
                    st.markdown("**🟢 긍정 핵심키워드**")
                    pos_path = os.path.join(WORDCLOUD_DIR, f"bucket_{i}_positive.png")
                    if os.path.exists(pos_path):
                        st.image(pos_path, width="stretch")
                    else:
                        st.caption("매칭된 키워드가 없습니다.")
                with kc2:
                    st.markdown("**🔴 부정 핵심키워드**")
                    neg_path = os.path.join(WORDCLOUD_DIR, f"bucket_{i}_negative.png")
                    if os.path.exists(neg_path):
                        st.image(neg_path, width="stretch")
                    else:
                        st.caption("매칭된 키워드가 없습니다.")

if active_tab == "😨 공포지수":
    st.subheader("VIX (공포지수)")
    st.caption(
        "S&P500 옵션 내재변동성으로 산출하는 CBOE 변동성지수. 20 이하는 안정, 30 이상은 공포 국면으로 흔히 해석됩니다. "
        "가장 널리 쓰이는 정량적 시장심리 지표입니다."
    )
    try:
        vix = get_series("VIXCLS", str(start_date), api_key)
        latest_vix = vix.dropna(subset=["value"]).iloc[-1]
        st.metric(f"최근 VIX ({latest_vix['date'].strftime('%Y-%m-%d')})", f"{latest_vix['value']:.2f}")
        render_zoomable_chart(
            vix, x="date", y="value", y_title="VIX", rule_y=20, rule_label="안정/공포 기준선(20)", key="vix"
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"데이터를 불러올 수 없습니다: {e}")

    st.divider()

    st.subheader("MOVE Index (채권시장 변동성지수)")
    st.caption(
        "ICE BofA MOVE Index. 미국 국채 옵션 내재변동성으로 산출하는 채권시장 버전 VIX입니다. "
        "값이 높을수록 금리·채권시장의 불안심리가 크다는 의미입니다."
    )
    try:
        move = get_yahoo_series("^MOVE", str(start_date), interval="1d")
        latest_move = move.iloc[-1]
        st.metric(f"최근 MOVE ({latest_move['date'].strftime('%Y-%m-%d')})", f"{latest_move['close']:.1f}")
        render_zoomable_chart(move, x="date", y="close", y_title="MOVE", key="move")
    except Exception as e:  # noqa: BLE001
        st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 종목 심리분석 ──────────────────────────────────────────
if active_tab == "🗣️ 종목 심리분석":
    st.subheader("종목 심리분석")
    st.caption(
        "네이버 금융 시가총액 상위 종목을 PER·PBR 가치평가 + 외국인/기관 수급으로 그룹화하고, "
        "종목토론실 여론(긍정/부정)이 실제 주가 수익률과 얼마나 일치하는지 분석합니다. "
        "감성분석은 키워드 사전 매칭 방식이며, 수급 거래대금은 (순매매수량 × 종가) 추정치입니다."
    )

    from stockanalyzer.jobs import pipeline_job

    if st.button("🔄 지금 다시 분석 (시가총액 상위 10종목)", key="stock_live_rerun", disabled=pipeline_job.status()["status"] == "running"):
        from stockanalyzer.live import run_pipeline_and_save

        if not pipeline_job.start(run_pipeline_and_save, pipeline_job.log):
            st.warning("이미 실행 중입니다.")
    render_pipeline_job_status()

    stock_data = get_stock_sentiment_data()
    if stock_data is None:
        st.info(
            "아직 생성된 분석 데이터가 없습니다. `python run_stock_pipeline.py`를 실행하거나 "
            "위 '지금 다시 분석' 버튼을 누르면 표시됩니다."
        )
    else:
        run_time = pd.to_datetime(stock_data["timestamp"]).strftime("%Y-%m-%d %H:%M")
        st.caption(f"기준 시각: {run_time} · 주기적 배치 갱신 데이터이며, 위 버튼으로 즉시 재수집할 수도 있습니다.")

        rec_df = pd.DataFrame(stock_data["recommendations"])
        corr_df = pd.DataFrame(stock_data["correlations"])

        if rec_df.empty:
            st.info("추천 데이터가 비어 있습니다.")
        else:
            rec_df = rec_df.sort_values("total_score", ascending=False).reset_index(drop=True)

            st.markdown("**종목 추천 (가치평가 + 수급 그룹)**")
            display_df = rec_df.assign(
                그룹=rec_df["group"].map(lambda g: f"{STOCK_GROUP_EMOJI.get(g, '')} {g}")
            )[["name", "per", "pbr", "value_score", "supply_score", "total_score", "그룹"]].rename(
                columns={
                    "name": "종목명", "per": "PER", "pbr": "PBR",
                    "value_score": "가치점수", "supply_score": "수급점수", "total_score": "종합점수",
                }
            )
            st.dataframe(display_df, width="stretch", hide_index=True)

            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**PER vs PBR (그룹별)**")
                scatter = alt.Chart(rec_df).mark_circle(size=140, opacity=0.85).encode(
                    x=alt.X("per:Q", title="PER (배)", scale=alt.Scale(zero=False)),
                    y=alt.Y("pbr:Q", title="PBR (배)", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "group:N", title="그룹",
                        scale=alt.Scale(domain=list(STOCK_GROUP_COLORS.keys()), range=list(STOCK_GROUP_COLORS.values())),
                        legend=alt.Legend(orient="bottom", columns=2),
                    ),
                    tooltip=[
                        alt.Tooltip("name:N", title="종목명"),
                        alt.Tooltip("per:Q", title="PER", format=".2f"),
                        alt.Tooltip("pbr:Q", title="PBR", format=".2f"),
                        alt.Tooltip("total_score:Q", title="종합점수", format=".1f"),
                    ],
                ).properties(height=320)
                st.altair_chart(scatter, width="stretch")
            with sc2:
                st.markdown("**종목별 종합 추천 점수**")
                bar = alt.Chart(rec_df).mark_bar().encode(
                    x=alt.X("total_score:Q", title="종합점수"),
                    y=alt.Y("name:N", title="", sort="-x"),
                    color=alt.Color(
                        "group:N", title="그룹",
                        scale=alt.Scale(domain=list(STOCK_GROUP_COLORS.keys()), range=list(STOCK_GROUP_COLORS.values())),
                        legend=None,
                    ),
                    tooltip=[alt.Tooltip("name:N", title="종목명"), alt.Tooltip("total_score:Q", title="종합점수", format=".1f")],
                ).properties(height=320)
                st.altair_chart(bar, width="stretch")

        st.divider()
        st.markdown("**커뮤니티(종목토론실) 여론 vs 실제 수익률 상관관계**")
        st.caption("양수(+)면 '긍정 여론일수록 실제로도 올랐다', 음수(-)면 여론과 실제 결과가 반대로 움직였다는 의미입니다.")
        if corr_df.empty:
            st.info("상관관계 데이터가 비어 있습니다.")
        else:
            corr_display = corr_df.rename(
                columns={"name": "종목명", "n_days": "관측일수", "sentiment_return_corr": "상관계수"}
            )[["종목명", "관측일수", "상관계수"]]
            st.dataframe(corr_display, width="stretch", hide_index=True)

            corr_valid = corr_df.dropna(subset=["sentiment_return_corr"])
            if not corr_valid.empty:
                corr_bar = alt.Chart(corr_valid).mark_bar().encode(
                    x=alt.X("sentiment_return_corr:Q", title="상관계수 (여론 vs 익일 수익률)"),
                    y=alt.Y("name:N", title="", sort="-x"),
                    color=alt.condition(
                        alt.datum.sentiment_return_corr >= 0, alt.value("#2e7d32"), alt.value("#c62828")
                    ),
                    tooltip=[alt.Tooltip("name:N", title="종목명"), alt.Tooltip("sentiment_return_corr:Q", title="상관계수", format=".2f")],
                ).properties(height=280)
                st.altair_chart(corr_bar, width="stretch")
            else:
                st.caption("관측일수가 부족해(종목당 3일 미만) 계산된 상관계수가 아직 없습니다. 데이터가 쌓일수록 채워집니다.")

if active_tab == "🔍 종목 검색·비교":
    st.subheader("종목 검색·비교")
    st.caption("원하는 종목을 최대 6개 골라 기간 전체 여론(긍정/부정) 우세 방향과 실제 등락 방향이 맞았는지 비교합니다. 실시간 크롤링이라 종목·기간에 따라 시간이 걸릴 수 있습니다.")
    with st.expander("펼치기", expanded=False):
        universe = _load_stock_json("stock_universe.json")
        if universe is None:
            from stockanalyzer.jobs import universe_job

            st.caption("종목 검색용 전체 상장목록이 아직 없습니다. 아래 버튼으로 한 번 만들어두면(코스피+코스닥 전종목, 1~2분) 이후 검색이 즉시 됩니다.")
            if st.button("전체 상장종목 목록 만들기", key="build_universe", disabled=universe_job.status()["status"] == "running"):
                from stockanalyzer.live import build_universe_and_save

                if not universe_job.start(build_universe_and_save, universe_job.log):
                    st.warning("이미 실행 중입니다.")
            render_universe_job_status()
        else:
            query = st.text_input("종목명 또는 코드 검색", key="stock_search_query")
            matches = []
            if query:
                q = query.strip().lower()
                matches = [s for s in universe["stocks"] if q in s["name"].lower() or q in s["code"]]
                matches.sort(key=lambda s: (not s["name"].lower().startswith(q), s["name"]))
                matches = matches[:15]

            # multiselect의 options는 검색어가 바뀔 때마다 새로 계산되는데, 이전 검색으로
            # 골라둔 종목이 새 options 목록에 없으면 streamlit이 session_state에서 그 선택을
            # 조용히 지워버린다(검색어를 바꾸는 순간 이전 선택이 사라져 1개만 남는 원인).
            # 검색으로 한 번이라도 등장했던 종목을 계속 누적해 options 풀로 유지해서 방지한다.
            options_pool = st.session_state.setdefault("stock_compare_options_pool", {})
            for s in matches:
                options_pool[f"{s['name']} ({s['code']})"] = s
            for label in st.session_state.get("stock_compare_select", []):
                options_pool.setdefault(label, {"name": label, "code": ""})

            match_labels = [f"{s['name']} ({s['code']})" for s in matches]
            prev_selected = st.session_state.get("stock_compare_select", [])
            option_labels = list(dict.fromkeys(match_labels + [l for l in prev_selected if l in options_pool]))

            selected_labels = st.multiselect(
                "비교할 종목 선택 (최대 6개)", option_labels, max_selections=6, key="stock_compare_select"
            )
            window_days = st.radio(
                "비교 기간", [1, 3, 5, 10, 20], horizontal=True, format_func=lambda d: f"최근 {d}일", key="stock_compare_days"
            )
            from stockanalyzer.jobs import compare_job

            if st.button(
                "비교분석 시작", key="stock_compare_run",
                disabled=not selected_labels or compare_job.status()["status"] == "running",
            ):
                from stockanalyzer.live import run_compare_and_save

                picked = [options_pool[label] for label in selected_labels]
                if not compare_job.start(run_compare_and_save, picked, window_days, compare_job.log):
                    st.warning("이미 다른 비교분석이 실행 중입니다. 잠시 후 다시 시도해주세요.")
            render_compare_job_status()

            compare_result = get_stock_compare_data()
            if compare_result and compare_result.get("results"):
                from stockanalyzer.analysis.compare import build_daily_table, compute_hit_rate

                st.caption(f"기준: 최근 {compare_result['days']}일 · {pd.to_datetime(compare_result['timestamp']).strftime('%Y-%m-%d %H:%M')}")

                LAG_OPTIONS = ["당일 여론 vs 당일 등락", "전일 여론 vs 다음 거래일 등락"]
                lag_label = st.radio(
                    "여론·주가 비교 시차", LAG_OPTIONS, horizontal=True, key="stock_compare_lag",
                    help="커뮤니티 반응이 다음 거래일 주가에 반영되는 경우가 많다는 가설을 반영해, "
                         "'당일 여론 vs 다음 거래일 등락'으로 바꿔 비교해볼 수 있습니다. 재크롤링 없이 즉시 재계산됩니다.",
                )
                lag_days = 1 if lag_label == LAG_OPTIONS[1] else 0

                # 종목별 일별 상세(daily_rows)는 lag 옵션에 따라 매번 다시 계산한다(재크롤링 불필요).
                daily_by_code = {}
                for r in compare_result["results"]:
                    rows = build_daily_table(r.get("daily_sentiment", {}), r.get("daily_price_changes", []), lag_days=lag_days)
                    daily_by_code[r["code"]] = {"rows": rows, "hit": compute_hit_rate(rows)}

                def _sentiment_label(row):
                    majority = row["sentiment_majority"]
                    if majority is None:
                        return "—"
                    if majority == "동률":
                        return majority
                    ratio = row["pos_ratio"] if majority == "긍정" else row["neg_ratio"]
                    return f"{majority}({ratio:.1f}%)" if pd.notna(ratio) else majority

                def _hit_rate_label(code):
                    hit = daily_by_code[code]["hit"]
                    return f"{hit['hit_rate']:.0f}% ({hit['judged_days']}일)" if hit["hit_rate"] is not None else "—"

                def _keyword_tags(row):
                    pos_kw, neg_kw = row.get("top_keywords_pos") or [], row.get("top_keywords_neg") or []
                    parts = []
                    if pos_kw:
                        parts.append("🟢" + ",".join(pos_kw))
                    if neg_kw:
                        parts.append("🔴" + ",".join(neg_kw))
                    return " ".join(parts) if parts else "—"

                cdf = pd.DataFrame(compare_result["results"])
                def _count_with_ratio(count, ratio):
                    return f"{count}({ratio:.1f}%)" if pd.notna(ratio) else str(count)

                cdf_display = cdf.assign(
                    일치여부=cdf["match"].map({True: "✅ 일치", False: "❌ 불일치", None: "—"}),
                    여론=cdf.apply(_sentiment_label, axis=1),
                    개미지수=cdf["code"].map(_hit_rate_label),
                    핫키워드=cdf.apply(_keyword_tags, axis=1),
                    긍정=cdf.apply(lambda r: _count_with_ratio(r["pos_count"], r.get("pos_ratio")), axis=1),
                    부정=cdf.apply(lambda r: _count_with_ratio(r["neg_count"], r.get("neg_ratio")), axis=1),
                )[[
                    "name", "price_now", "price_change_pct",
                    "긍정", "부정", "여론", "price_direction", "일치여부", "개미지수", "핫키워드",
                ]].rename(columns={
                    "name": "종목명", "price_now": "현재가",
                    "price_change_pct": "기간등락률(%)", "price_direction": "실제방향",
                })
                st.dataframe(cdf_display, width="stretch", hide_index=True)
                st.caption(
                    "개미지수 = 선택한 기간 중 신뢰도 미달(하루 게시글 20건 미만)인 날을 뺀 나머지 날의 "
                    "여론-주가 방향 일치율. 핫키워드는 감성 사전 매칭이 아니라 제목 명사 빈도 기반 상위 3개."
                )

                st.markdown("**종목별 일별 트렌드**")
                for r in compare_result["results"]:
                    daily_rows = daily_by_code[r["code"]]["rows"]
                    hit = daily_by_code[r["code"]]["hit"]
                    hit_text = f"개미지수 {hit['hit_rate']:.0f}%" if hit["hit_rate"] is not None else "개미지수 —"
                    with st.expander(f"📊 {r['name']} · {hit_text}", expanded=False):
                        if not daily_rows:
                            st.caption("일별 데이터가 없습니다.")
                            continue

                        daily_df = pd.DataFrame(daily_rows)
                        daily_df["net_sentiment"] = daily_df["pos_count"] - daily_df["neg_count"]
                        daily_df["match_icon"] = daily_df["match"].map({True: "✅", False: "❌"}).fillna("")
                        max_abs = daily_df["net_sentiment"].abs().max() or 1
                        daily_df["marker_y"] = max_abs * 1.25

                        # x축은 날짜 문자열(YYYY-MM-DD)을 temporal(T)로 넘겨 "7.16" 같은 짧은 포맷 +
                        # 가로 라벨(labelAngle=0)을 쓴다. y축 제목은 길면 서로 겹쳐 보여서 짧게 줄였다.
                        x_enc = alt.X("date:T", title="날짜", axis=alt.Axis(format="%-m.%-d", labelAngle=0))
                        bar = alt.Chart(daily_df).mark_bar().encode(
                            x=x_enc,
                            y=alt.Y("net_sentiment:Q", title="여론지수", axis=alt.Axis(titlePadding=8)),
                            color=alt.condition(alt.datum.net_sentiment >= 0, alt.value("#2e7d32"), alt.value("#c62828")),
                            tooltip=[
                                alt.Tooltip("date:T", title="날짜", format="%Y-%m-%d"), alt.Tooltip("pos_count:Q", title="긍정글"),
                                alt.Tooltip("neg_count:Q", title="부정글"), alt.Tooltip("total_posts:Q", title="전체"),
                            ],
                        )
                        line = alt.Chart(daily_df).mark_line(point=True, color="#4C78A8").encode(
                            x=x_enc,
                            y=alt.Y("price_change_pct:Q", title="등락률(%)", axis=alt.Axis(titlePadding=8)),
                            tooltip=[alt.Tooltip("date:T", title="날짜", format="%Y-%m-%d"), alt.Tooltip("price_change_pct:Q", title="등락률(%)", format="+.2f")],
                        )
                        markers = alt.Chart(daily_df).mark_text(fontSize=14).encode(
                            x=x_enc, y=alt.Y("marker_y:Q"), text="match_icon:N",
                        )
                        st.altair_chart(
                            alt.layer(bar, markers, line).resolve_scale(y="independent").properties(height=280),
                            width="stretch",
                        )

                        detail_display = daily_df.assign(
                            감성지수=daily_df["pos_ratio"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—"),
                            주가등락=daily_df["price_change_pct"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—"),
                            예측일치=daily_df["match"].map({True: "✅ 일치", False: "❌ 불일치", None: "—"}),
                            버즈상태=daily_df.apply(
                                lambda r2: "⚠️ 신뢰도 미달" if r2["low_buzz"] else ("🔥 버즈 급증" if r2["buzz_spike"] else ""), axis=1
                            ),
                        )[["date", "pos_count", "neg_count", "감성지수", "주가등락", "예측일치", "버즈상태"]].rename(columns={
                            "date": "날짜", "pos_count": "긍정글", "neg_count": "부정글",
                        })
                        st.dataframe(detail_display, width="stretch", hide_index=True)

                with st.expander("원문 게시글 보기 (긍정/부정 라벨)", expanded=False):
                    label_filter = st.multiselect(
                        "라벨 필터", ["긍정", "중립", "부정"], default=["긍정", "중립", "부정"], key="posts_label_filter"
                    )
                    for r in compare_result["results"]:
                        posts_sample = [p for p in (r.get("posts_sample") or []) if p["label"] in label_filter]
                        st.markdown(f"**{r['name']}** · 전체 {r.get('total_posts', 0)}건 중 최근 {len(r.get('posts_sample') or [])}건(필터 적용 {len(posts_sample)}건)")
                        if posts_sample:
                            st.dataframe(
                                pd.DataFrame(posts_sample).rename(
                                    columns={"date": "날짜", "title": "제목", "label": "라벨"}
                                ),
                                width="stretch", hide_index=True, height=200,
                            )
                        else:
                            st.caption("해당 라벨의 게시글이 없습니다.")

if active_tab == "🏭 업종분석":
    st.subheader("종목분석")
    st.caption(
        "선택한 업종의 종목을 ROE·EPS성장률·PER·PBR·부채비율(가치점수) + 외국인·기관 순매수 강도·"
        "거래대금 팽창비율(수급점수)로 그룹화합니다. 실시간 크롤링이라 다소 걸릴 수 있습니다."
    )
    with st.expander("펼치기", expanded=True):
        from stockanalyzer.crawler.sector import BROAD_SECTOR_GROUPS

        sector_name = st.selectbox("업종 선택", list(BROAD_SECTOR_GROUPS.keys()), key="sector_select")

        filter_c1, filter_c2 = st.columns(2)
        with filter_c1:
            sort_basis = st.radio(
                "정렬 기준", ["거래대금", "시가총액"], horizontal=True, key="sector_sort_basis",
                help="시가총액 정렬은 '종목 검색·비교' 탭에서 전체 상장종목 목록을 먼저 만들어둬야 합니다.",
            )
        with filter_c2:
            top_n = st.selectbox("상위 N종목", [5, 10, 20, 30], index=3, key="sector_top_n")

        st.markdown("**종목추가** (자동 선정 상위 N 밖의 종목도 함께 비교하고 싶을 때)")
        universe_for_extra = _load_stock_json("stock_universe.json")
        if universe_for_extra is None:
            st.caption("'종목 검색·비교' 탭에서 전체 상장종목 목록을 먼저 만들면 종목추가 검색을 쓸 수 있습니다.")
            extra_picks = []
        else:
            extra_query = st.text_input("종목명 또는 코드 검색", key="sector_extra_query")
            extra_matches = []
            if extra_query:
                eq = extra_query.strip().lower()
                extra_matches = [
                    s for s in universe_for_extra["stocks"]
                    if eq in s["name"].lower() or eq in s["code"]
                ][:15]
                extra_matches.sort(key=lambda s: (not s["name"].lower().startswith(eq), s["name"]))

            extra_pool = st.session_state.setdefault("sector_extra_options_pool", {})
            for s in extra_matches:
                extra_pool[f"{s['name']} ({s['code']})"] = s
            for label in st.session_state.get("sector_extra_select", []):
                extra_pool.setdefault(label, {"name": label, "code": ""})

            extra_match_labels = [f"{s['name']} ({s['code']})" for s in extra_matches]
            prev_extra = st.session_state.get("sector_extra_select", [])
            extra_option_labels = list(dict.fromkeys(extra_match_labels + [l for l in prev_extra if l in extra_pool]))

            extra_selected_labels = st.multiselect(
                "추가할 종목 선택 (최대 5개)", extra_option_labels, max_selections=5, key="sector_extra_select",
            )
            extra_picks = [extra_pool[label] for label in extra_selected_labels]

        from stockanalyzer.jobs import sector_job

        if st.button("업종분석 시작", key="sector_run", disabled=sector_job.status()["status"] == "running"):
            from stockanalyzer.live import run_sector_and_save

            if not sector_job.start(run_sector_and_save, sector_name, sort_basis, top_n, extra_picks, sector_job.log):
                st.warning("이미 다른 업종분석이 실행 중입니다. 잠시 후 다시 시도해주세요.")
        render_sector_job_status()

        sector_result = get_stock_sector_data()
        if sector_result and sector_result.get("recommendations"):
            extra_note = f" + 수동추가 {sector_result['manual_extra_count']}종목" if sector_result.get("manual_extra_count") else ""
            st.caption(
                f"'{sector_result['sector_name']}' 업종 {sector_result['total_in_sector']}종목 중 "
                f"{sector_result.get('sort_basis', '거래대금')} 상위 {sector_result['analyzed_count']}종목 분석{extra_note} · "
                f"{pd.to_datetime(sector_result['timestamp']).strftime('%Y-%m-%d %H:%M')}"
            )
            sdf = pd.DataFrame(sector_result["recommendations"]).sort_values("total_score", ascending=False)
            sdf = sdf.assign(
                그룹=sdf["group"].map(lambda g: f"{STOCK_GROUP_EMOJI.get(g, '')} {g}"),
                종목명=sdf.apply(lambda r: f"➕ {r['name']}" if r.get("manually_added") else r["name"], axis=1),
            )
            # 컬럼이 13개라 한 표에 다 넣으면 그룹 컬럼이 잘려 보여서, 가치점수 관련/수급점수 관련
            # 두 표로 나눠 각자 폭에 여유를 준다(종목명은 두 표 모두에 넣어 대조가 되게 유지).
            value_display = sdf[
                ["종목명", "per", "pbr", "roe", "eps_growth", "debt_ratio", "value_score"]
            ].rename(columns={
                "per": "PER", "pbr": "PBR", "roe": "ROE(%)", "eps_growth": "EPS성장률(%)",
                "debt_ratio": "부채비율(%)", "value_score": "가치점수",
            })
            supply_display = sdf[
                ["종목명", "foreign_strength", "inst_strength", "turnover_expansion", "supply_score", "total_score", "그룹"]
            ].rename(columns={
                "foreign_strength": "외국인순매수강도", "inst_strength": "기관순매수강도",
                "turnover_expansion": "거래대금증가율", "supply_score": "수급점수", "total_score": "종합점수",
            })
            st.markdown("**가치점수**")
            st.dataframe(value_display, width="stretch", hide_index=True)
            st.markdown("**수급점수 · 종합점수 · 그룹**")
            st.dataframe(supply_display, width="stretch", hide_index=True)
            st.caption("➕ 표시는 상위 N 밖에서 수동으로 추가한 종목입니다. EV/EBITDA·FCF·연기금 순매수는 네이버 금융에서 안정적으로 크롤링할 수 없어 가치점수/수급점수 산식에서 제외하고 나머지 지표 가중치를 재조정했습니다.")

# ── 노트 아카이브 ────────────────────────────────────────────
@st.dialog("노트", width="large")
def show_note_dialog(row: pd.Series):
    date_label = row["note_date"].strftime("%Y-%m-%d") if pd.notna(row["note_date"]) else "날짜 미상"
    weekday = f" ({row['weekday']})" if pd.notna(row.get("weekday")) else ""
    st.subheader(row["title"])
    st.caption(f"{date_label}{weekday}")

    data_uri = note_image_data_uri(row.get("image_file"))
    if data_uri:
        st.markdown(
            f'<img src="{data_uri}" style="width:100%;display:block;border-radius:8px;">',
            unsafe_allow_html=True,
        )

    if row["tags"]:
        tag_chips = "".join(
            f'<span style="background:#4C78A8;color:#fff;padding:2px 10px;border-radius:12px;'
            f'font-size:12px;margin-right:6px;display:inline-block;">{t}</span>'
            for t in row["tags"]
        )
        st.markdown(f'<div style="margin:10px 0 6px;">{tag_chips}</div>', unsafe_allow_html=True)

    if pd.notna(row.get("executive_summary")):
        has_chart = bool(row.get("has_chart"))
        labels = (
            {"key_points": "핵심 수치·트렌드", "macro": "거시경제적 의미", "policy": "통화정책·금융시장 파급효과"}
            if has_chart
            else {"key_points": "핵심 주제·내용", "macro": "메커니즘·인과관계", "policy": "투자·자산배분 시사점"}
        )
        key_points_html = "".join(f"<li>{kp}</li>" for kp in row["key_points"])
        st.markdown(
            f"""
            <div style="border-radius:8px;padding:14px 16px;background:rgba(127,127,127,0.12);">
                <div style="font-size:13px;font-weight:600;margin-bottom:4px;">{labels['key_points']}</div>
                <ul style="margin:0 0 12px;padding-left:18px;font-size:13px;line-height:1.5;">{key_points_html}</ul>
                <div style="font-size:13px;font-weight:600;margin-bottom:4px;">{labels['macro']}</div>
                <div style="font-size:14px;line-height:1.5;margin-bottom:12px;">{row['macro_interpretation']}</div>
                <div style="font-size:13px;font-weight:600;margin-bottom:4px;">{labels['policy']}</div>
                <div style="font-size:14px;line-height:1.5;margin-bottom:12px;">{row['policy_or_strategy_implication']}</div>
                <div style="font-size:13px;font-weight:600;margin-bottom:4px;">📌 종합 요약</div>
                <div style="font-size:14px;line-height:1.5;font-weight:500;">{row['executive_summary']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.write(row["summary"])
        for kp in row["key_points"]:
            st.markdown(f"- {kp}")

    if pd.notna(row.get("source")):
        st.caption(f"출처: {row['source']}")


if active_tab == "📓 노트 아카이브":
    st.subheader("손글씨 경제공부 노트 아카이브")
    st.caption(
        "직접 정리한 거시경제·시장 공부 노트를 Gemini Vision으로 구조화한 아카이브입니다. "
        "태그로 필터링해 특정 주제에 대한 과거 생각의 흐름을 시간순으로 되짚어볼 수 있습니다."
    )

    notes_df = get_notes()
    if notes_df.empty:
        st.info("아직 인덱싱된 노트가 없습니다. notes_ocr.py로 노트 사진을 먼저 처리해주세요.")
    else:
        st.caption(f"총 {len(notes_df)}건의 노트가 인덱싱되어 있습니다.")
        selected_tags = st.multiselect("태그 필터", NOTE_TAGS)

        filtered = notes_df
        if selected_tags:
            filtered = filtered[filtered["tags"].apply(lambda ts: any(t in ts for t in selected_tags))]
        st.caption(f"{len(filtered)}건 표시 중")

        for _, row in filtered.iterrows():
            date_label = row["note_date"].strftime("%Y-%m-%d") if pd.notna(row["note_date"]) else "날짜 미상"
            weekday = f" ({row['weekday']})" if pd.notna(row.get("weekday")) else ""
            with st.container(border=True):
                col1, col2 = st.columns([6, 1])
                with col1:
                    st.markdown(f"**{date_label}{weekday}** · {row['title']}")
                    if row["tags"]:
                        st.caption(" · ".join(row["tags"]))
                with col2:
                    if st.button("열기", key=f"open_{row['file']}", width="stretch"):
                        show_note_dialog(row)

# ── 뉴스 ────────────────────────────────────────────────────
if active_tab == "📰 뉴스":
    st.subheader("어제자 경제 뉴스 Top 10")
    st.caption(
        "네이버 뉴스 랭킹(언론사별 최다조회 기사) 중 경제 키워드가 포함된 기사를 언론사당 1건씩, "
        "조회순위 기준으로 모은 목록입니다. 네이버가 카테고리 통합 조회수 랭킹을 공개 API로 제공하지 "
        "않아 키워드 매칭으로 근사한 결과이니 참고용으로 봐주세요."
    )

    yesterday_kst = datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)
    news_date_str = yesterday_kst.strftime("%Y%m%d")

    try:
        news_items = get_news(news_date_str, top_n=10)
    except Exception as e:  # noqa: BLE001
        news_items = []
        st.error(f"뉴스를 불러오지 못했습니다: {e}")

    st.caption(f"기준일: {yesterday_kst.strftime('%Y-%m-%d')} (KST)")

    if not news_items:
        st.info("해당 날짜에 경제 키워드로 분류된 뉴스를 찾지 못했습니다.")
    else:
        for i, item in enumerate(news_items, 1):
            st.markdown(f"**{i}. [{item['title']}]({item['url']})**")
            st.caption(item["press"])
