import requests
import pandas as pd

ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

# 8.1.2. 경기종합지수 (2020=100)
COMPOSITE_INDEX_STAT_CODE = "901Y067"
LEADING_INDEX_ITEM = "I16E"  # 선행지수순환변동치
COINCIDENT_INDEX_ITEM = "I16D"  # 동행지수순환변동치


def fetch_ecos_monthly(item_code: str, api_key: str, start_yyyymm: str, end_yyyymm: str) -> pd.DataFrame:
    """한국은행 ECOS에서 경기종합지수(순환변동치) 월별 시계열을 가져온다."""
    url = f"{ECOS_URL}/{api_key}/json/kr/1/500/{COMPOSITE_INDEX_STAT_CODE}/M/{start_yyyymm}/{end_yyyymm}/{item_code}"
    resp = requests.get(url, timeout=15)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        # 원본 예외 메시지에는 api_key가 URL 경로에 그대로 들어있어 화면에 노출될 수 있으므로 감춘다.
        raise requests.HTTPError(f"ECOS API 요청 실패 (status {resp.status_code}, item_code={item_code})") from None
    payload = resp.json()

    if "RESULT" in payload:
        raise ValueError(payload["RESULT"].get("MESSAGE", "ECOS API 오류"))

    rows = payload.get("StatisticSearch", {}).get("row", [])
    df = pd.DataFrame(rows)[["TIME", "DATA_VALUE"]]
    df["date"] = pd.to_datetime(df["TIME"], format="%Y%m")
    df["value"] = pd.to_numeric(df["DATA_VALUE"], errors="coerce")
    return df[["date", "value"]].dropna().reset_index(drop=True)
