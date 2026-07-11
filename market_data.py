from datetime import datetime, timezone

import pandas as pd
import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_yahoo_series(
    symbol: str, start_date: str, end_date: str | None = None, interval: str = "1mo"
) -> pd.DataFrame:
    """Yahoo Finance 공개 차트 API에서 시세를 가져온다. symbol 예: '^GSPC', '^SOX', '^KS11'."""
    period1 = int(pd.Timestamp(start_date, tz="UTC").timestamp())
    period2 = (
        int(pd.Timestamp(end_date, tz="UTC").timestamp())
        if end_date
        else int(datetime.now(timezone.utc).timestamp())
    )
    resp = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"period1": period1, "period2": period2, "interval": interval},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s"), "close": closes}).dropna()
    if interval == "1mo":
        df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    else:
        df["date"] = df["date"].dt.normalize()
    df = df.drop_duplicates(subset="date", keep="last")
    return df.sort_values("date").reset_index(drop=True)
