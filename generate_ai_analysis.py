"""
8개 경제지표(Core CPI/PCE/WTI/BEI/비농업고용/실업률/평균시급/신규실업수당청구건수)의
Gemini AI 해석을 미리 생성해 ai_analysis_cache.json에 커밋한다.

배포된 Streamlit Cloud 앱은 컨테이너가 재시작될 때마다(예: 매일 감성데이터 갱신에 따른
자동 재배포) ai_analysis_cache.json이 통째로 초기화되는데, 그때마다 사용자가 "🔍 AI해석"
버튼을 눌러야 Gemini를 다시 호출해 느린 로딩이 발생했다. 이 스크립트를 GitHub Actions에서
주기적으로 돌려 캐시 파일 자체를 리포에 커밋해두면, 실제 지표가 새로 발표된 경우에만
Gemini가 호출되고(ai_analysis.py의 cache_key 로직 그대로 재사용) 그 외에는 배포 직후부터
바로 캐시된 텍스트가 표시된다.

app.py와 완전히 동일한 series_id/cache_key 로직을 써야 캐시 키가 일치한다 — app.py의
해당 지표 섹션을 수정하면 이 스크립트도 함께 맞춰야 한다.
"""
import os

import pandas as pd

from ai_analysis import get_indicator_analysis
from fred_client import add_change_columns, fetch_fred_series

FRED_API_KEY = os.environ["FRED_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
START_DATE = "2018-01-01"


def series_context(df: pd.DataFrame, col: str, label: str, n: int = 6, suffix: str = "", signed: bool = True) -> str:
    recent = df.dropna(subset=[col]).tail(n)
    fmt = "{:+.2f}" if signed else "{:.2f}"
    lines = [f"{row['date'].strftime('%Y-%m-%d')}: {fmt.format(row[col])}{suffix}" for _, row in recent.iterrows()]
    return f"{label} 최근 추이:\n" + "\n".join(lines)


def get_series(series_id: str) -> pd.DataFrame:
    return add_change_columns(fetch_fred_series(series_id, FRED_API_KEY, START_DATE))


def main() -> None:
    cpi = get_series("CPILFESL")
    cpi_latest_date = cpi.dropna(subset=["MoM%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
    get_indicator_analysis(
        "cpi", "Core CPI (MoM)", series_context(cpi, "MoM%", "Core CPI MoM", suffix="%"), cpi_latest_date, GEMINI_API_KEY
    )

    pce = get_series("PCEPILFE")
    pce_latest_date = pce.dropna(subset=["MoM%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
    get_indicator_analysis(
        "pce", "Core PCE (MoM)", series_context(pce, "MoM%", "Core PCE MoM", suffix="%"), pce_latest_date, GEMINI_API_KEY
    )

    wti = get_series("DCOILWTICO")
    wti_latest = wti.dropna(subset=["value"]).iloc[-1]
    iso = wti_latest["date"].isocalendar()
    wti_week_key = f"{iso.year}-W{iso.week:02d}"
    get_indicator_analysis(
        "wti", "WTI 유가", series_context(wti, "value", "WTI 현물가", suffix="$", signed=False), wti_week_key, GEMINI_API_KEY
    )

    # BEI는 자체 발표 주기가 없는 매일 갱신 시장 데이터라, CPI 발표일에 맞춰 함께 갱신한다(기존 app.py 사양).
    df5 = get_series("T5YIE")[["date", "value"]].rename(columns={"value": "5년 기대인플레이션"})
    df10 = get_series("T10YIE")[["date", "value"]].rename(columns={"value": "10년 기대인플레이션"})
    bei_merged = pd.merge(df5, df10, on="date", how="inner")
    bei_context = (
        series_context(bei_merged.rename(columns={"5년 기대인플레이션": "value"}), "value", "5년 기대인플레이션", suffix="%", signed=False)
        + "\n"
        + series_context(bei_merged.rename(columns={"10년 기대인플레이션": "value"}), "value", "10년 기대인플레이션", suffix="%", signed=False)
    )
    get_indicator_analysis("bei", "기대인플레이션 (BEI)", bei_context, cpi_latest_date, GEMINI_API_KEY)

    payrolls = get_series("PAYEMS")
    payrolls_latest_date = payrolls.dropna(subset=["MoM_chg"]).iloc[-1]["date"].strftime("%Y-%m-%d")
    get_indicator_analysis(
        "payrolls",
        "비농업 고용 (Nonfarm Payrolls)",
        series_context(payrolls, "MoM_chg", "비농업 고용 전월 대비 증감(천 명)", suffix="K"),
        payrolls_latest_date,
        GEMINI_API_KEY,
    )

    unrate = get_series("UNRATE")
    unrate_latest_date = unrate.dropna(subset=["value"]).iloc[-1]["date"].strftime("%Y-%m-%d")
    get_indicator_analysis(
        "unrate", "실업률", series_context(unrate, "value", "실업률(%)", suffix="%", signed=False), unrate_latest_date, GEMINI_API_KEY
    )

    wages = get_series("CES0500000003")
    wages_latest_date = wages.dropna(subset=["YoY%"]).iloc[-1]["date"].strftime("%Y-%m-%d")
    get_indicator_analysis(
        "wages", "평균시급 (YoY)", series_context(wages, "YoY%", "평균시급 YoY", suffix="%"), wages_latest_date, GEMINI_API_KEY
    )

    claims = get_series("ICSA")
    claims_latest = claims.dropna(subset=["value"]).iloc[-1]
    get_indicator_analysis(
        "claims",
        "신규 실업수당 청구건수",
        series_context(claims, "value", "신규 실업수당 청구건수", signed=False),
        claims_latest["date"].strftime("%Y-%m-%d"),
        GEMINI_API_KEY,
    )


if __name__ == "__main__":
    main()
