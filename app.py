import json
import os
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
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
    /* 참고자료1 표: 좁은 화면(모바일 포함)에서 셀 텍스트가 줄바꿈으로 쪼개지지 않도록
       표 자체를 가로 스크롤시킨다(칸이 눌려서 읽기 힘들어지는 문제 방지). */
    div[class*="st-key-reftable_scroll"] {
        overflow-x: auto;
        padding-bottom: 0.6rem;
    }
    div[class*="st-key-reftable_scroll"] table {
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

REFERENCE_TABLE_MD = """
| 지표 | 핵심 정의 (투자 관점) | 최적 출처 | 수집 방식 | 발표 주기 |
|---|---|---|---|---|
| **Core CPI (MoM)** | 에너지·식품 제외 소비자물가 전월비 변화율. 연준이 가장 주목하는 근원 인플레 지표 | **FRED** (`CPILFESL`) | API (무료 키) | 매월 중순 |
| **Core PCE (MoM)** | 에너지·식품 제외 개인소비지출 물가지수. 연준이 공식 타겟(2%)으로 삼는 지표 | **FRED** (`PCEPILFE`) | API | 매월 말 |
| **WTI 유가** | 서부텍사스산 원유 현물가($/배럴). 에너지 인플레이션과 에너지주 실적에 직결되는 선행 변수 | **FRED** (`DCOILWTICO`) | API | 매 영업일 |
| **기대인플레이션 (BEI)** | 국채-물가연동국채(TIPS) 스프레드로 산출한 시장 기대인플레이션(5년·10년물) | **FRED** (`T5YIE`, `T10YIE`) | API | 매 영업일 |
| **비농업 고용** | 비농업 부문 신규 고용자 수 증감. 경기 모멘텀의 대표 선행 신호 | **FRED** (`PAYEMS`) | API | 매월 첫째 금요일 |
| **실업률** | 경제활동인구 중 실업자 비율. 연준 이중책무(고용) 판단 근거 | **FRED** (`UNRATE`) | API | NFP와 동시 발표 |
| **평균시급 (AHE)** | 시간당 평균 임금, 전년비(YoY)가 임금발 인플레 압력 판단 기준 | **FRED** (`CES0500000003`) | API | NFP와 동시 발표 |
| **신규 실업수당 청구건수** | 매주 발표되는 초기 실업수당 청구 건수. 고용 냉각을 가장 빨리 포착하는 주간 선행 지표 | **FRED** (`ICSA`) | API | 매주 목요일 |
| **ISM 서비스 PMI** | 50 기준 서비스업 경기 확장/위축 판단. 소비 중심 미국 경제 특성상 중요도 높음 | **ISM 공식 발표 / investing.com 캘린더** | 무료 API 없음 → 수동 입력 | 매월 3영업일경 |
| **FOMC (점도표·파월 기자회견)** | 연준 위원들의 금리 전망 중간값(점도표), 통화정책 방향성의 핵심 | **federalreserve.gov** (SEP, 성명서, 기자회견) | 무료 API 없음 → 수동 입력 + 링크 | 연 8회(점도표는 3·6·9·12월) |
| **한국 경기종합지수 (선행·동행)** | 순환변동치 기준, 향후 경기 방향(선행)·현재 경기 국면(동행) 판단 | **한국은행 ECOS** (통계표 `901Y067`) | API (무료 키) | 매월 |
| **美 2Y·10Y 국채금리 · Fed 정책금리** | 단기·장기 금리, 스프레드(10Y-2Y)는 대표적 경기침체 예고 지표. 정책금리는 FOMC 결정치 | **FRED** (`DGS2`, `DGS10`, `DFEDTARU`) | API | 매 영업일(정책금리는 FOMC 시) |
| **美 국채 수익률곡선** | 1개월~30년 전 만기 금리를 연결한 곡선. 우하향(역전)되면 경기침체 예고 신호로 흔히 해석 | **FRED** (`DGS1MO`~`DGS30`) | API | 매 영업일 |
| **반도체 버블 지수 (SOX)** | PHLX 반도체지수, 닷컴버블 대비 현재 AI 랠리의 과열 정도를 비교 | **Yahoo Finance** (`^SOX`) | API(비공식 공개 차트) | 매 영업일 |
| **Shiller PE (CAPE Ratio)** | S&P500 10년 평균 실질이익 기준 경기조정 PER. 장기평균(~17) 대비 고평가/저평가 판단 | **multpl.com** (Robert Shiller 데이터) | 무료 API 없음 → 스크래핑 | 매월 |
| **버핏지수 근사치** | 시가총액(S&P500) ÷ GDP, 장기평균=100 지수화. 워런 버핏이 참고하는 밸류에이션 지표 근사치 | **Yahoo Finance**(`^GSPC`) + **FRED**(`GDP`) | API | 매 영업일(GDP는 분기) |
| **VIX (공포지수)** | S&P500 옵션 내재변동성. 20 이하 안정, 30 이상 공포 국면으로 흔히 해석 | **FRED** (`VIXCLS`) | API | 매 영업일 |
| **MOVE Index** | ICE BofA MOVE Index. 美 국채 옵션 내재변동성 기준, 채권시장판 VIX | **Yahoo Finance** (`^MOVE`) | API(비공식 공개 차트) | 매 영업일 |
| **KOSPI·KOSDAQ·Nasdaq·Dow** | 한·미 대표 증시 지수 4종. 시장 탭에서 장중 1시간 단위로 갱신 | **Yahoo Finance** (`^KS11`,`^KQ11`,`^IXIC`,`^DJI`) | API(비공식 공개 차트) | 매 영업일 |
| **국내주식 인간지표** | 국내 주식 커뮤니티(디시인사이드) 게시글 키워드 매칭 기반 긍정/부정 심리 분류 | 디시인사이드 국내주식 갤러리 | 크롤링 | 매일(전일자 기준) |
| **경제 뉴스 Top 10** | 네이버 뉴스 랭킹 중 경제 키워드가 포함된 전일자 기사 | 네이버 뉴스 랭킹 | 크롤링 | 매일(전일자 기준) |
"""

# ── 헤더 (제목 + 우상단 메뉴) ────────────────────────────────
title_col, menu_col = st.columns([0.92, 0.08])
with title_col:
    st.title("📊 거시경제 투자심리 대시보드")
    st.caption("주식 투자 참고용 초안 · 데이터 출처: FRED / ISM / 연준(federalreserve.gov) / ECOS / Yahoo Finance")
with menu_col:
    with st.popover("☰"):
        with st.expander("참고자료1. 지표별 최적 출처 요약"):
            with st.container(key="reftable_scroll"):
                st.markdown(REFERENCE_TABLE_MD)

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
    if st.button("🔍 AI해석", key=f"analysis_{indicator_key}", width="stretch"):
        show_analysis_dialog(title, indicator_key, title, context, cache_key)


TAB_LABELS = [
    "📈 시장", "🐟 물가", "👷 고용", "🏭 경기·연준", "💵 금리", "📐 가치평가", "🧠 인간지표", "🗣️ 종목 심리분석",
    "📓 노트 아카이브", "📰 뉴스",
]

# st.tabs()는 화면에 안 보이는 탭이어도 매 rerun마다 안의 코드를 전부 실행해서,
# 재배포 직후처럼 캐시가 비어있을 때 8개 탭 몫의 외부 API 호출(~20건)이 한 번에 몰리는
# 원인이 됐다. segmented_control은 선택값을 코드에서 알 수 있어 선택된 탭만 실행하도록
# 바꿀 수 있다(진짜 지연 로딩) — 대신 밑줄 탭 대신 알약형 버튼 UI로 바뀐다.
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = TAB_LABELS[0]

_selected_tab = st.segmented_control(
    "탭 선택", TAB_LABELS, default=st.session_state["active_tab"], label_visibility="collapsed"
)
if _selected_tab:
    st.session_state["active_tab"] = _selected_tab
active_tab = st.session_state["active_tab"]

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
            st.subheader("신규 실업수당 청구건수")
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
                        "신규 실업수당 청구건수",
                        series_context(df, "value", "신규 실업수당 청구건수", signed=False),
                        latest["date"].strftime("%Y-%m-%d"),
                    )
                render_zoomable_chart(df, x="date", y="value", y_title="건", key="claims")
            except Exception as e:  # noqa: BLE001
                st.warning(f"데이터를 불러올 수 없습니다: {e}")

# ── 경기·연준 (한국 경기종합지수 + 수동 입력 지표) ──────────
if active_tab == "🏭 경기·연준":
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

    st.subheader("ISM 서비스 PMI")
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

    st.divider()

    st.subheader("FOMC (점도표 · 파월 기자회견)")
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
            ].rename(columns={"value": "한국은행 기준금리"})
            merged = pd.merge(merged, kr_base, on="date", how="left")
            merged["한국은행 기준금리"] = merged["한국은행 기준금리"].ffill()
            rate_cols.append("한국은행 기준금리")
            rate_colors.append("#08306B")  # 진한 파란색
        else:
            st.caption("사이드바에 ECOS API Key를 입력하면 한국은행 기준금리도 함께 표시됩니다.")

        c1, c2 = st.columns(2)
        with c1:
            latest = merged.iloc[-1]
            prev = merged.iloc[-2]
            latest_date = latest["date"].strftime("%Y-%m-%d")
            for label, col in [("2년물", "2Y"), ("10년물", "10Y")]:
                delta_abs = latest[col] - prev[col]
                delta_pct = delta_abs / prev[col] * 100 if prev[col] else 0.0
                st.metric(
                    f"{label} ({latest_date})",
                    f"{latest[col]:.2f}%",
                    delta=f"{delta_abs:+.3f}%p ({delta_pct:+.2f}%)",
                )
        with c2:
            spread = latest["10Y-2Y 스프레드"]
            st.metric("10Y-2Y 스프레드", f"{spread:+.2f}%p", delta="역전 중" if spread < 0 else "정상")
            st.metric("Fed 정책금리(상단)", f"{latest['Fed 정책금리(상단)']:.2f}%")
            if "한국은행 기준금리" in merged and pd.notna(latest["한국은행 기준금리"]):
                st.metric("한국은행 기준금리", f"{latest['한국은행 기준금리']:.2f}%")

        rate_notes = notes_for_tags(get_notes(), ["Fed정책/금리", "수익률곡선/침체신호"])
        if not rate_notes.empty:
            st.caption("점선은 이 기간에 작성한 관련 노트입니다. 마우스를 올리면 제목·요약이 보입니다.")

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
            notes_df=rate_notes,
        )
        st.markdown("**장단기금리차 (10Y-2Y 스프레드)**")
        render_zoomable_chart(
            merged, x="date", y="10Y-2Y 스프레드", y_title="%p", rule_y=0, rule_label="역전 기준선(0)",
            key="rates_spread", notes_df=rate_notes,
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

# ── 가치평가 ────────────────────────────────────────────────
if active_tab == "📐 가치평가":
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
if active_tab == "🧠 인간지표":
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

    st.divider()

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

    st.divider()
    st.markdown("**🔍 종목 검색·비교**")
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
            options = {f"{s['name']} ({s['code']})": s for s in matches}
            selected_labels = st.multiselect(
                "비교할 종목 선택 (최대 6개)", list(options.keys()), max_selections=6, key="stock_compare_select"
            )
            window_days = st.radio(
                "비교 기간", [1, 3, 7, 30], horizontal=True, format_func=lambda d: f"최근 {d}일", key="stock_compare_days"
            )
            from stockanalyzer.jobs import compare_job

            if st.button(
                "비교분석 시작", key="stock_compare_run",
                disabled=not selected_labels or compare_job.status()["status"] == "running",
            ):
                from stockanalyzer.live import run_compare_and_save

                picked = [options[label] for label in selected_labels]
                if not compare_job.start(run_compare_and_save, picked, window_days, compare_job.log):
                    st.warning("이미 다른 비교분석이 실행 중입니다. 잠시 후 다시 시도해주세요.")
            render_compare_job_status()

            compare_result = get_stock_compare_data()
            if compare_result and compare_result.get("results"):
                st.caption(f"기준: 최근 {compare_result['days']}일 · {pd.to_datetime(compare_result['timestamp']).strftime('%Y-%m-%d %H:%M')}")
                cdf = pd.DataFrame(compare_result["results"])
                cdf_display = cdf.assign(
                    일치=cdf["match"].map({True: "✅ 일치", False: "❌ 불일치", None: "—"})
                )[[
                    "name", "per", "pbr", "price_now", "price_change_pct",
                    "pos_count", "neg_count", "sentiment_majority", "price_direction", "일치",
                ]].rename(columns={
                    "name": "종목명", "per": "PER", "pbr": "PBR", "price_now": "현재가",
                    "price_change_pct": "기간등락률(%)", "pos_count": "긍정글", "neg_count": "부정글",
                    "sentiment_majority": "여론", "price_direction": "실제방향",
                })
                st.dataframe(cdf_display, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**🏭 업종분석**")
    st.caption("선택한 업종의 거래대금 상위 종목을 PER·PBR 가치평가 + 수급으로 그룹화합니다. 실시간 크롤링(최대 30종목)이라 다소 걸릴 수 있습니다.")
    with st.expander("펼치기", expanded=False):
        from stockanalyzer.crawler.sector import BROAD_SECTOR_GROUPS

        sector_name = st.selectbox("업종 선택", list(BROAD_SECTOR_GROUPS.keys()), key="sector_select")

        from stockanalyzer.jobs import sector_job

        if st.button("업종분석 시작", key="sector_run", disabled=sector_job.status()["status"] == "running"):
            from stockanalyzer.live import run_sector_and_save

            if not sector_job.start(run_sector_and_save, sector_name, sector_job.log):
                st.warning("이미 다른 업종분석이 실행 중입니다. 잠시 후 다시 시도해주세요.")
        render_sector_job_status()

        sector_result = get_stock_sector_data()
        if sector_result and sector_result.get("recommendations"):
            st.caption(
                f"'{sector_result['sector_name']}' 업종 {sector_result['total_in_sector']}종목 중 "
                f"거래대금 상위 {sector_result['analyzed_count']}종목 분석 · "
                f"{pd.to_datetime(sector_result['timestamp']).strftime('%Y-%m-%d %H:%M')}"
            )
            sdf = pd.DataFrame(sector_result["recommendations"]).sort_values("total_score", ascending=False)
            sdf_display = sdf.assign(
                그룹=sdf["group"].map(lambda g: f"{STOCK_GROUP_EMOJI.get(g, '')} {g}")
            )[["name", "per", "pbr", "value_score", "supply_score", "total_score", "그룹"]].rename(columns={
                "name": "종목명", "per": "PER", "pbr": "PBR",
                "value_score": "가치점수", "supply_score": "수급점수", "total_score": "종합점수",
            })
            st.dataframe(sdf_display, width="stretch", hide_index=True)

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
