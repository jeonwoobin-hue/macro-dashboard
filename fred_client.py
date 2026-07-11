import requests
import pandas as pd

FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series(series_id: str, api_key: str, start_date: str) -> pd.DataFrame:
    """FRED(Federal Reserve Economic Data)에서 시계열 데이터를 가져온다."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
    }
    resp = requests.get(FRED_OBS_URL, params=params, timeout=15)
    resp.raise_for_status()
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
