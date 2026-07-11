import io
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from wordcloud import WordCloud

from charts import zoom_chart
from ecos_client import COINCIDENT_INDEX_ITEM, LEADING_INDEX_ITEM, fetch_ecos_monthly
from fred_client import add_change_columns, fetch_fred_series
from market_data import fetch_yahoo_series
from news_client import fetch_top_economic_news

load_dotenv()


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
st.markdown(
    """
    <style>
    div[class*="st-key-scrollrow"] div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap;
        overflow-x: auto;
        padding-bottom: 0.6rem;
    }
    div[class*="st-key-scrollrow"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        min-width: 340px;
        flex: 0 0 340px;
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
| **Nonfarm Payrolls** | 비농업 부문 신규 고용자 수 증감. 경기 모멘텀의 대표 선행 신호 | **FRED** (`PAYEMS`) | API | 매월 첫째 금요일 |
| **실업률** | 경제활동인구 중 실업자 비율. 연준 이중책무(고용) 판단 근거 | **FRED** (`UNRATE`) | API | NFP와 동시 발표 |
| **평균시급 (AHE)** | 시간당 평균 임금, 전년비(YoY)가 임금발 인플레 압력 판단 기준 | **FRED** (`CES0500000003`) | API | NFP와 동시 발표 |
| **ISM 서비스 PMI** | 50 기준 서비스업 경기 확장/위축 판단. 소비 중심 미국 경제 특성상 중요도 높음 | **ISM 공식 발표 / investing.com 캘린더** | 무료 API 없음 → 수동 입력 | 매월 3영업일경 |
| **FOMC (점도표·파월 기자회견)** | 연준 위원들의 금리 전망 중간값(점도표), 통화정책 방향성의 핵심 | **federalreserve.gov** (SEP, 성명서, 기자회견) | 무료 API 없음 → 수동 입력 + 링크 | 연 8회(점도표는 3·6·9·12월) |
| **美 2Y·10Y 국채금리** | 단기·장기 금리, 스프레드(10Y-2Y)는 대표적 경기침체 예고 지표 | **FRED** (`DGS2`, `DGS10`) | API | 매 영업일 |
"""

# ── 헤더 (제목 + 우상단 메뉴) ────────────────────────────────
title_col, menu_col = st.columns([0.92, 0.08])
with title_col:
    st.title("📊 거시경제 투자심리 대시보드")
    st.caption("주식 투자 참고용 초안 · 데이터 출처: FRED / ISM / 연준(federalreserve.gov) / ECOS / Yahoo Finance")
with menu_col:
    with st.popover("☰"):
        with st.expander("참고자료1. 지표별 최적 출처 요약"):
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

    start_date = st.date_input("조회 시작일", value=pd.to_datetime("2018-01-01"))
    st.divider()
    st.caption("데이터는 1시간 캐시됩니다. 최신값이 필요하면 새로고침하세요.")

if not api_key:
    st.warning("사이드바에 FRED API Key를 입력해야 자동 지표(물가·고용·금리)를 불러올 수 있습니다.")
    st.stop()


@st.cache_data(ttl=3600)
def get_series(series_id: str, start: str, key: str) -> pd.DataFrame:
    df = fetch_fred_series(series_id, key, start)
    return add_change_columns(df)


@st.cache_data(ttl=3600)
def get_yahoo_series(symbol: str, start: str, interval: str = "1mo") -> pd.DataFrame:
    return fetch_yahoo_series(symbol, start, interval=interval)


@st.cache_data(ttl=3600)
def get_ecos_series(item_code: str, key: str, start_yyyymm: str, end_yyyymm: str) -> pd.DataFrame:
    return fetch_ecos_monthly(item_code, key, start_yyyymm, end_yyyymm)


KOREAN_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothic-Regular.ttf")


@st.cache_data(ttl=3600)
def make_wordcloud_png(keywords: list[dict], colormap: str) -> bytes | None:
    freqs = {k["keyword"]: k["count"] for k in keywords}
    if not freqs:
        return None
    wc = WordCloud(
        font_path=KOREAN_FONT_PATH,
        width=600,
        height=400,
        background_color="white",
        colormap=colormap,
        prefer_horizontal=0.9,
    ).generate_from_frequencies(freqs)
    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return buf.getvalue()


@st.cache_data(ttl=3600)
def get_news(date_str: str, top_n: int = 10) -> list[dict]:
    return fetch_top_economic_news(date_str, top_n=top_n)


def show_latest_metric(df: pd.DataFrame, col: str, label: str, suffix: str = "%"):
    latest = df.dropna(subset=[col]).iloc[-1]
    prev = df.dropna(subset=[col]).iloc[-2] if len(df.dropna(subset=[col])) > 1 else None
    delta = None if prev is None else round(latest[col] - prev[col], 2)
    st.metric(
        label=f"{label} ({latest['date'].strftime('%Y-%m')})",
        value=f"{latest[col]:.2f}{suffix}",
        delta=f"{delta:+.2f}{suffix}p" if delta is not None else None,
    )


tab_market, tab_inflation, tab_labor, tab_growth_fed, tab_rates, tab_valuation, tab_sentiment, tab_news = st.tabs(
    ["📈 시장", "🔥 물가", "👷 고용", "🏭 경기·연준", "💵 금리", "📐 가치평가", "🧠 인간지표", "📰 뉴스"]
)

# ── 시장 ────────────────────────────────────────────────────
with tab_market:
    with st.container(key="scrollrow_market"):
        c1, c2, c3, c4 = st.columns(4)

        market_indices = [
            (c1, "^KS11", "KOSPI", "한국 대표 증시 지수. 국내 대형주 중심."),
            (c2, "^KQ11", "KOSDAQ", "한국 성장·중소형주 중심 지수. 코스피 대비 변동성이 큼."),
            (c3, "^IXIC", "Nasdaq", "미국 기술주 중심 지수. 성장주·금리 민감도가 높음."),
            (c4, "^DJI", "Dow Jones", "미국 대형 우량주 30종목 지수. 경기민감·전통산업 비중이 큼."),
        ]
        for col, symbol, name, desc in market_indices:
            with col:
                st.subheader(name)
                st.caption(desc)
                df = get_yahoo_series(symbol, str(start_date), interval="1d")
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                chg_pct = (latest["close"] - prev["close"]) / prev["close"] * 100
                st.metric(
                    f"최근 종가 ({latest['date'].strftime('%Y-%m-%d')})",
                    f"{latest['close']:,.2f}",
                    delta=f"{chg_pct:+.2f}%",
                )
                st.altair_chart(zoom_chart(df, x="date", y="close", y_title="종가"), width="stretch")

# ── 물가 ────────────────────────────────────────────────────
with tab_inflation:
    with st.container(key="scrollrow_inflation"):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.subheader("Core CPI (MoM)")
            st.caption("에너지·식품을 제외한 소비자물가지수의 전월 대비 변화율. 연준의 근원 인플레이션 판단 지표.")
            df = get_series("CPILFESL", str(start_date), api_key)
            show_latest_metric(df, "MoM%", "최근 발표 MoM")
            st.altair_chart(
                zoom_chart(df, x="date", y="MoM%", y_title="MoM (%)", rule_y=0.2, rule_label="연준 목표"),
                width="stretch",
            )

        with c2:
            st.subheader("Core PCE (MoM)")
            st.caption("에너지·식품을 제외한 개인소비지출 물가지수 전월비. 연준이 공식 목표(2%)로 삼는 지표.")
            df = get_series("PCEPILFE", str(start_date), api_key)
            show_latest_metric(df, "MoM%", "최근 발표 MoM")
            st.altair_chart(zoom_chart(df, x="date", y="MoM%", y_title="MoM (%)"), width="stretch")

        with c3:
            st.subheader("WTI 유가")
            st.caption("서부텍사스산 원유 현물가($/배럴). 에너지 인플레이션과 에너지주 실적에 직결되는 선행 변수.")
            df = get_series("DCOILWTICO", str(start_date), api_key)
            latest = df.dropna(subset=["value"]).iloc[-1]
            prev = df.dropna(subset=["value"]).iloc[-2]
            st.metric(
                f"최근 종가 ({latest['date'].strftime('%Y-%m-%d')})",
                f"${latest['value']:.2f}",
                delta=f"{latest['value'] - prev['value']:+.2f}",
            )
            st.altair_chart(zoom_chart(df, x="date", y="value", y_title="$/배럴"), width="stretch")

        with c4:
            st.subheader("기대인플레이션 (BEI)")
            st.caption("국채-물가연동국채(TIPS) 스프레드로 산출한 시장 기대인플레이션. 5년물·10년물 비교.")
            df5 = get_series("T5YIE", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "5년 기대인플레이션"})
            df10y = get_series("T10YIE", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "10년 기대인플레이션"})
            bei_merged = pd.merge(df5, df10y, on="date", how="inner")
            latest = bei_merged.iloc[-1]
            st.metric(f"5년 BEI ({latest['date'].strftime('%Y-%m-%d')})", f"{latest['5년 기대인플레이션']:.2f}%")
            bei_long = bei_merged.melt(id_vars="date", var_name="구분", value_name="값")
            st.altair_chart(
                zoom_chart(
                    bei_long,
                    x="date",
                    y="값",
                    color="구분",
                    color_domain=["5년 기대인플레이션", "10년 기대인플레이션"],
                    color_range=["#4C78A8", "#F58518"],
                    y_title="%",
                ),
                width="stretch",
            )

# ── 고용 ────────────────────────────────────────────────────
with tab_labor:
    with st.container(key="scrollrow_labor"):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.subheader("Nonfarm Payrolls")
            st.caption("비농업 부문 신규 고용자 수(전월 대비 증감, 천 명). 경기 모멘텀의 대표 선행 신호.")
            df = get_series("PAYEMS", str(start_date), api_key)
            show_latest_metric(df, "MoM_chg", "전월 대비 증감", suffix="K")
            st.altair_chart(
                zoom_chart(df, x="date", y="MoM_chg", y_title="천 명", mark="bar"), width="stretch"
            )

        with c2:
            st.subheader("실업률")
            st.caption("경제활동인구 중 실업자 비율. 연준 이중책무(물가·고용) 중 고용 측면 판단 근거.")
            df = get_series("UNRATE", str(start_date), api_key)
            show_latest_metric(df, "value", "최근 실업률")
            st.altair_chart(zoom_chart(df, x="date", y="value", y_title="%"), width="stretch")

        with c3:
            st.subheader("평균시급 (YoY)")
            st.caption("시간당 평균 임금 전년 대비 상승률. 임금발 인플레이션 압력을 가늠하는 지표.")
            df = get_series("CES0500000003", str(start_date), api_key)
            show_latest_metric(df, "YoY%", "최근 발표 YoY")
            st.altair_chart(zoom_chart(df, x="date", y="YoY%", y_title="YoY (%)"), width="stretch")

        with c4:
            st.subheader("신규 실업수당 청구건수")
            st.caption("매주 발표되는 초기 실업수당 청구 건수. 고용 냉각을 가장 빨리 포착하는 주간 선행 지표.")
            df = get_series("ICSA", str(start_date), api_key)
            latest = df.dropna(subset=["value"]).iloc[-1]
            prev = df.dropna(subset=["value"]).iloc[-2]
            st.metric(
                f"최근 발표 ({latest['date'].strftime('%Y-%m-%d')})",
                f"{latest['value']:,.0f}건",
                delta=f"{latest['value'] - prev['value']:+,.0f}",
            )
            st.altair_chart(zoom_chart(df, x="date", y="value", y_title="건"), width="stretch")

# ── 경기·연준 (한국 경기종합지수 + 수동 입력 지표) ──────────
with tab_growth_fed:
    st.subheader("한국 경기종합지수 (선행·동행 순환변동치)")
    st.caption(
        "선행지수순환변동치는 향후 경기 방향, 동행지수순환변동치는 현재 경기 국면을 보여줍니다. "
        "100을 기준으로 위/아래가 경기 확장/수축 국면을 의미합니다. 출처: 한국은행 ECOS (통계표 901Y067)."
    )
    if not ecos_key:
        st.info("사이드바에 ECOS API Key를 입력하면 자동으로 표시됩니다. 무료 발급: https://ecos.bok.or.kr/api/")
    else:
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
        st.altair_chart(
            zoom_chart(
                long_kr,
                x="date",
                y="값",
                color="구분",
                color_domain=["선행종합지수(순환변동치)", "동행종합지수(순환변동치)"],
                color_range=["#F58518", "#4C78A8"],
                y_title="지수(2020=100)",
            ),
            width="stretch",
        )

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
        st.altair_chart(
            zoom_chart(
                chart_df, x="release_date", y="pmi", y_title="PMI", rule_y=50, rule_label="기준선(50)"
            ),
            width="stretch",
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
        st.altair_chart(
            zoom_chart(long_df, x="meeting_date", y="값", color="구분", y_title="금리(%)"), width="stretch"
        )
    else:
        st.info("위 표에 회의일(meeting_date)과 금리·점도표 값을 입력하면 추세 차트가 표시됩니다.")

# ── 금리 ────────────────────────────────────────────────────
with tab_rates:
    st.subheader("美 2년물·10년물 국채금리 & 연준 정책금리")
    st.caption(
        "단기(2Y)·장기(10Y) 국채금리와 연준 정책금리(상단, 빨간선). "
        "10Y-2Y 스프레드가 역전(음수)되면 대표적인 경기침체 예고 신호로 해석됩니다."
    )

    df2 = get_series("DGS2", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "2Y"})
    df10 = get_series("DGS10", str(start_date), api_key)[["date", "value"]].rename(columns={"value": "10Y"})
    dff = get_series("DFEDTARU", str(start_date), api_key)[["date", "value"]].rename(
        columns={"value": "Fed 정책금리(상단)"}
    )
    merged = pd.merge(df2, df10, on="date", how="inner")
    merged["10Y-2Y 스프레드"] = merged["10Y"] - merged["2Y"]
    merged = pd.merge(merged, dff, on="date", how="left")
    merged["Fed 정책금리(상단)"] = merged["Fed 정책금리(상단)"].ffill()

    c1, c2 = st.columns(2)
    with c1:
        latest = merged.iloc[-1]
        st.metric("2Y", f"{latest['2Y']:.2f}%")
        st.metric("10Y", f"{latest['10Y']:.2f}%")
    with c2:
        spread = latest["10Y-2Y 스프레드"]
        st.metric("10Y-2Y 스프레드", f"{spread:+.2f}%p", delta="역전 중" if spread < 0 else "정상")
        st.metric("Fed 정책금리(상단)", f"{latest['Fed 정책금리(상단)']:.2f}%")

    long_rates = merged.melt(
        id_vars="date", value_vars=["2Y", "10Y", "Fed 정책금리(상단)"], var_name="구분", value_name="금리(%)"
    ).dropna(subset=["금리(%)"])
    st.altair_chart(
        zoom_chart(
            long_rates,
            x="date",
            y="금리(%)",
            color="구분",
            color_domain=["2Y", "10Y", "Fed 정책금리(상단)"],
            color_range=["#4C78A8", "#54A24B", "#E45756"],
            y_title="금리(%)",
        ),
        width="stretch",
    )
    st.markdown("**장단기금리차 (10Y-2Y 스프레드)**")
    st.altair_chart(
        zoom_chart(merged, x="date", y="10Y-2Y 스프레드", y_title="%p", rule_y=0, rule_label="역전 기준선(0)"),
        width="stretch",
    )

# ── 가치평가 ────────────────────────────────────────────────
with tab_valuation:
    st.subheader("반도체 버블 지수 (닷컴버블 vs AI·반도체 랠리)")
    st.caption(
        "PHLX 반도체지수(SOX)를 각 랠리 시작월 = 100으로 지수화해 상승폭을 직접 비교합니다. "
        "닷컴버블(1995~2002)과 현재 AI·반도체 랠리(2019~)의 궤적을 겹쳐서 과열 정도를 가늠해볼 수 있습니다."
    )
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

        st.altair_chart(
            zoom_chart(
                shiller_df, x="date", y="shiller_pe", y_title="Shiller PE", rule_y=17, rule_label="장기평균(~17)"
            ),
            width="stretch",
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
        st.altair_chart(
            zoom_chart(buffett_view, x="date", y="지수화", y_title="버핏지수(장기평균=100)"), width="stretch"
        )

# ── 인간지표 (시장 심리) ──────────────────────────────────────
with tab_sentiment:
    st.subheader("국내주식 인간지표")
    st.caption(
        "디시인사이드 국내주식 갤러리의 전날 게시글을 시간대 4구간으로 나눠, "
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
            f"총 수집 게시글 {sentiment_data['total_posts_scanned']:,}건 · "
            f"생성 시각: {sentiment_data['generated_at'][:16].replace('T', ' ')}"
        )

        bucket_labels = list(sentiment_data["buckets"].keys())
        bucket_tabs = st.tabs(bucket_labels)
        for label, bucket_tab in zip(bucket_labels, bucket_tabs):
            bucket = sentiment_data["buckets"][label]
            with bucket_tab:
                st.caption(
                    f"수집 게시글 {bucket['total_posts']:,}건 · "
                    f"긍정 분류 {bucket['positive_posts']}건 · 부정 분류 {bucket['negative_posts']}건"
                )
                kc1, kc2 = st.columns(2)
                with kc1:
                    st.markdown("**🟢 긍정 핵심키워드**")
                    png = make_wordcloud_png(bucket["positive_keywords"], "Greens")
                    if png:
                        st.image(png, width="stretch")
                    else:
                        st.caption("매칭된 키워드가 없습니다.")
                with kc2:
                    st.markdown("**🔴 부정 핵심키워드**")
                    png = make_wordcloud_png(bucket["negative_keywords"], "Reds")
                    if png:
                        st.image(png, width="stretch")
                    else:
                        st.caption("매칭된 키워드가 없습니다.")

    st.divider()

    st.subheader("VIX (공포지수)")
    st.caption(
        "S&P500 옵션 내재변동성으로 산출하는 CBOE 변동성지수. 20 이하는 안정, 30 이상은 공포 국면으로 흔히 해석됩니다. "
        "가장 널리 쓰이는 정량적 시장심리 지표입니다."
    )
    vix = get_series("VIXCLS", str(start_date), api_key)
    latest_vix = vix.dropna(subset=["value"]).iloc[-1]
    st.metric(f"최근 VIX ({latest_vix['date'].strftime('%Y-%m-%d')})", f"{latest_vix['value']:.2f}")
    st.altair_chart(
        zoom_chart(vix, x="date", y="value", y_title="VIX", rule_y=20, rule_label="안정/공포 기준선(20)"),
        width="stretch",
    )

# ── 뉴스 ────────────────────────────────────────────────────
with tab_news:
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
