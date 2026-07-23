"""업종 내 종목에 가치점수(ROE·EPS성장률·PER·PBR·부채비율) + 수급점수(외국인·기관 순매수 강도 +
거래대금 팽창비율)를 매겨 추천 표를 만든다. 채점 로직은 value_supply_score.py 참고.

원본(SentiStock)은 여기서 report.py의 matplotlib 차트도 함께 생성했지만, 이 대시보드에
이식하면서 뺐다 — Streamlit 배포 런타임에 matplotlib을 새로 끌고 들어오지 않기 위함
(차트는 app.py에서 Altair로 그린다). MEMORY.md "종목 심리분석 탭" 섹션 참고."""
import json

import pandas as pd

from stockanalyzer.crawler.sector import fetch_stocks_for_broad_sector
from stockanalyzer.crawler.fundamentals import fetch_fundamentals_extended
from stockanalyzer.crawler.supply_demand import fetch_supply_demand
from stockanalyzer.crawler.price import fetch_price_history
from stockanalyzer.analysis.value_supply_score import build_advanced_value_supply_table
from stockanalyzer.config import SUPPLY_DEMAND_PAGES, DATA_DIR

TOP_N_BY_TRADING_VALUE = 30  # 업종 내 전 종목을 다 크롤링하면 너무 오래 걸려 상위만 분석
SUPPLY_WINDOW_DAYS = 20
TWIN_BUY_LOOKBACK_DAYS = 5


def _load_market_cap_map() -> dict:
    """stock_universe.json(종목 검색·비교 탭에서 미리 만들어둔 전체 상장종목 목록)에서
    code -> market_cap(억원) 맵을 읽어온다. 없으면 빈 dict(=시가총액 정렬 불가)."""
    path = DATA_DIR / "stock_universe.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {s["code"]: s.get("market_cap") for s in payload.get("stocks", []) if s.get("market_cap")}


def _analyze_one_stock(code: str, name: str) -> dict:
    fundamentals = fetch_fundamentals_extended(code)
    market_cap = fundamentals.get("market_cap")  # 억원
    market_cap_won = market_cap * 1e8 if market_cap else None

    supply_rows = fetch_supply_demand(code, pages=SUPPLY_DEMAND_PAGES)[:SUPPLY_WINDOW_DAYS]
    foreign_sum = sum((r["foreign_net_value_est"] or 0) for r in supply_rows)
    inst_sum = sum((r["inst_net_value_est"] or 0) for r in supply_rows)
    twin_buy_days = sum(
        1 for r in supply_rows[:TWIN_BUY_LOOKBACK_DAYS]
        if (r["foreign_net_qty"] or 0) > 0 and (r["inst_net_qty"] or 0) > 0
    )

    foreign_strength = (foreign_sum / market_cap_won * 100) if market_cap_won else None
    inst_strength = (inst_sum / market_cap_won * 100) if market_cap_won else None

    price_rows = fetch_price_history(code, pages=2)[:SUPPLY_WINDOW_DAYS]
    daily_values = [(r["close"] or 0) * (r["volume"] or 0) for r in price_rows if r["close"] and r["volume"]]
    turnover_expansion = None
    if daily_values:
        avg_value = sum(daily_values) / len(daily_values)
        today_value = daily_values[0]  # price_rows는 최신순
        if avg_value:
            turnover_expansion = today_value / avg_value * 100

    return {
        "code": code,
        "name": name,
        "per": fundamentals.get("per"),
        "pbr": fundamentals.get("pbr"),
        "roe": fundamentals.get("roe"),
        "eps_growth": fundamentals.get("eps_growth"),
        "debt_ratio": fundamentals.get("debt_ratio"),
        "market_cap": market_cap,
        "foreign_strength": foreign_strength,
        "inst_strength": inst_strength,
        "turnover_expansion": turnover_expansion,
        "twin_buy_days": twin_buy_days,
    }


def analyze_sector(
    sector_name: str,
    sort_basis: str = "거래대금",
    top_n: int = TOP_N_BY_TRADING_VALUE,
    extra_stocks: list | None = None,
    log=print,
) -> dict:
    log(f"'{sector_name}' 업종 종목 목록 조회 중...")
    stocks = fetch_stocks_for_broad_sector(sector_name)

    if sort_basis == "시가총액":
        market_cap_map = _load_market_cap_map()
        for s in stocks:
            s["market_cap"] = market_cap_map.get(s["code"])
        ranked = [s for s in stocks if s.get("market_cap")]
        ranked.sort(key=lambda s: s["market_cap"], reverse=True)
        if not market_cap_map:
            log("시가총액 데이터가 없습니다('종목 검색·비교' 탭에서 전체 상장종목 목록을 먼저 만들어주세요). 거래대금 기준으로 대체합니다.")
            ranked = [s for s in stocks if s.get("trading_value")]
            ranked.sort(key=lambda s: s["trading_value"], reverse=True)
    else:
        ranked = [s for s in stocks if s.get("trading_value")]
        ranked.sort(key=lambda s: s["trading_value"], reverse=True)

    top_stocks = ranked[:top_n]

    if not top_stocks and not extra_stocks:
        return {
            "sector_name": sector_name, "sort_basis": sort_basis,
            "recommendations": [], "total_in_sector": len(stocks), "analyzed_count": 0,
        }

    top_codes = {s["code"] for s in top_stocks}
    manual_extras = [s for s in (extra_stocks or []) if s["code"] not in top_codes]

    log(f"{len(top_stocks) + len(manual_extras)}종목의 재무·수급 데이터 수집 중 (ROE/EPS성장률/부채비율/외국인·기관 수급)...")
    rows = []
    for s in top_stocks + manual_extras:
        log(f"  - {s['name']} ({s['code']})")
        row = _analyze_one_stock(s["code"], s["name"])
        row["manually_added"] = s["code"] not in top_codes
        rows.append(row)

    rec_df = build_advanced_value_supply_table(rows)

    rank_map = {s["code"]: i + 1 for i, s in enumerate(top_stocks)}
    rec_df["sector_rank"] = rec_df["code"].map(rank_map)

    return {
        "sector_name": sector_name,
        "sort_basis": sort_basis,
        "recommendations": json.loads(rec_df.to_json(orient="records")),
        "total_in_sector": len(stocks),
        "analyzed_count": len(top_stocks),
        "manual_extra_count": len(manual_extras),
    }
