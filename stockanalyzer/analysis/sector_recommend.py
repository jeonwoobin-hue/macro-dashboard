"""업종 내 종목에 PER/PBR(가치) + 수급 점수를 매겨 추천 표를 만든다.
기존 시가총액 상위 10개 전용이던 recommend.py의 채점 로직(build_value_supply_table)을
그대로 재사용해 '선택한 업종(14개 큰 그룹)의 거래대금 상위 N종목'에 적용한다.

원본(SentiStock)은 여기서 report.py의 matplotlib 차트도 함께 생성했지만, 이 대시보드에
이식하면서 뺐다 — Streamlit 배포 런타임에 matplotlib을 새로 끌고 들어오지 않기 위함
(차트는 app.py에서 Altair로 그린다). MEMORY.md "종목 심리분석 탭" 섹션 참고."""
import json

import pandas as pd

from stockanalyzer.crawler.sector import fetch_stocks_for_broad_sector
from stockanalyzer.crawler.fundamentals import fetch_per_pbr
from stockanalyzer.crawler.supply_demand import fetch_supply_demand
from stockanalyzer.analysis.recommend import build_value_supply_table
from stockanalyzer.config import SUPPLY_DEMAND_PAGES

TOP_N_BY_TRADING_VALUE = 30  # 업종 내 전 종목을 다 크롤링하면 너무 오래 걸려 거래대금 상위만 분석


def analyze_sector(sector_name: str, top_n: int = TOP_N_BY_TRADING_VALUE, log=print) -> dict:
    log(f"'{sector_name}' 업종 종목 목록 조회 중...")
    stocks = fetch_stocks_for_broad_sector(sector_name)
    stocks = [s for s in stocks if s.get("trading_value")]
    stocks.sort(key=lambda s: s["trading_value"], reverse=True)
    top_stocks = stocks[:top_n]

    if not top_stocks:
        return {
            "sector_name": sector_name,
            "recommendations": [], "total_in_sector": len(stocks), "analyzed_count": 0,
        }

    log(f"거래대금 상위 {len(top_stocks)}종목의 PER/PBR·수급 데이터 수집 중...")
    fundamentals_rows = []
    supply_rows = []
    for s in top_stocks:
        log(f"  - {s['name']} ({s['code']})")
        per_pbr = fetch_per_pbr(s["code"])
        fundamentals_rows.append(
            {"code": s["code"], "name": s["name"], "per": per_pbr["per"], "pbr": per_pbr["pbr"]}
        )

        supply = fetch_supply_demand(s["code"], pages=SUPPLY_DEMAND_PAGES)
        net_value_sum = sum(
            (r["inst_net_value_est"] or 0) + (r["foreign_net_value_est"] or 0) for r in supply
        )
        supply_rows.append({"code": s["code"], "supply_value_sum": net_value_sum})

    rec_df = build_value_supply_table(pd.DataFrame(fundamentals_rows), pd.DataFrame(supply_rows))

    trading_value_rank = {s["code"]: i + 1 for i, s in enumerate(top_stocks)}
    rec_df["trading_value_rank"] = rec_df["code"].map(trading_value_rank)

    return {
        "sector_name": sector_name,
        "recommendations": json.loads(rec_df.to_json(orient="records")),
        "total_in_sector": len(stocks),
        "analyzed_count": len(top_stocks),
    }
