import requests
import pandas as pd

from http_utils import get_with_retry

FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series(series_id: str, api_key: str, start_date: str) -> pd.DataFrame:
    """FRED(Federal Reserve Economic Data)에서 시계열 데이터를 가져온다."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
    }
    resp = get_with_retry(FRED_OBS_URL, params=params, timeout=15)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        # 원본 예외 메시지에는 api_key가 포함된 URL이 그대로 들어있어 화면에 노출될 수 있으므로 감춘다.
        raise requests.HTTPError(f"FRED API 요청 실패 (status {resp.status_code}, series_id={series_id})") from None
    observations = resp.json().get("observations", [])
    df = pd.DataFrame(observations)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"]).reset_index(drop=True)


def add_change_columns(df: pd.DataFrame) -> pd.DataFrame:
    """월별 시계열에 전월비(MoM%), 전년비(YoY%), 전월 증감(절대값) 컬럼을 추가한다."""
    df = df.copy()
    df["MoM%"] = df["value"].pct_change() * 100
    df["YoY%"] = df["value"].pct_change(12) * 100
    df["MoM_chg"] = df["value"].diff()
    return df
