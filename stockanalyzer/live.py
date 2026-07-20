"""배포된 Streamlit 앱에서 사용자가 직접 트리거하는 라이브 분석("지금 다시 분석"/"비교분석"/
"업종분석")이 실행되는 곳. 셋 다 stockanalyzer.async_job.AsyncJob으로 백그라운드 스레드에서
돌아가고, app.py의 폴링 프래그먼트가 진행 상황을 읽어 화면에 표시한다 — 버튼 클릭 핸들러에서
직접 블로킹 호출하면 그동안 같은 서버의 다른 방문자도 멈추기 때문(MEMORY.md 참고).

run_pipeline_live()는 main.py의 run_pipeline()과 크롤링·분석 로직은 동일하지만,
`from stockanalyzer import report`(matplotlib 차트/마크다운 리포트 생성) 단계는 뺐다 — app.py는
결과를 Altair로 직접 그리므로 필요 없고, 배포 런타임에 matplotlib을 새로 들여오지 않기 위함이다.
오프라인/CI 갱신(run_stock_pipeline.py)은 계속 main.py의 원본 run_pipeline()을 쓴다.
"""
import json
import os
from datetime import datetime

import pandas as pd

from stockanalyzer.analysis.correlate import build_sentiment_return_table, compute_correlation_by_stock
from stockanalyzer.analysis.recommend import build_value_supply_table
from stockanalyzer.analysis.sentiment import score_posts
from stockanalyzer.config import BOARD_PAGES, DATA_DIR, PRICE_HISTORY_PAGES, SUPPLY_DEMAND_PAGES, TOP_N_STOCKS
from stockanalyzer.crawler.community import fetch_board_posts
from stockanalyzer.crawler.fundamentals import fetch_per_pbr
from stockanalyzer.crawler.market_cap import fetch_top_market_cap
from stockanalyzer.crawler.price import fetch_price_history
from stockanalyzer.crawler.supply_demand import fetch_supply_demand
from stockanalyzer.storage import (
    get_conn, init_db, save_board_posts, save_fundamentals_snapshot,
    save_price_history, save_stock, save_supply_demand,
)

SUPPLY_WINDOW_DAYS = 20


def _records(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records"))


def _load_analysis_frames(stocks: list, today: str):
    codes = [s["code"] for s in stocks]
    name_map = {s["code"]: s["name"] for s in stocks}
    placeholders = ",".join("?" * len(codes))

    with get_conn() as conn:
        fundamentals_df = pd.read_sql_query(
            f"""SELECT code, per, pbr FROM fundamentals_snapshot
                WHERE snapshot_date = ? AND code IN ({placeholders})""",
            conn, params=[today, *codes],
        )
        fundamentals_df["name"] = fundamentals_df["code"].map(name_map)

        supply_df = pd.read_sql_query(
            f"""SELECT code, date, inst_net_value_est, foreign_net_value_est
                FROM supply_demand WHERE code IN ({placeholders})
                ORDER BY code, date DESC""",
            conn, params=codes,
        )
        supply_recent = (
            supply_df.groupby("code").head(SUPPLY_WINDOW_DAYS)
            .assign(net_value=lambda d: d["inst_net_value_est"] + d["foreign_net_value_est"])
            .groupby("code")["net_value"].sum()
            .reset_index(name="supply_value_sum")
        )

        board_df = pd.read_sql_query(
            f"""SELECT code, date, sentiment_score FROM board_posts
                WHERE code IN ({placeholders})""",
            conn, params=codes,
        )

        price_df = pd.read_sql_query(
            f"""SELECT code, date, close FROM price_history WHERE code IN ({placeholders})""",
            conn, params=codes,
        )

    return fundamentals_df, supply_recent, board_df, price_df, name_map


def run_pipeline_live(log=print) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    init_db()

    log(f"시가총액 상위 {TOP_N_STOCKS}개 종목 조회 중...")
    stocks = fetch_top_market_cap(TOP_N_STOCKS)

    with get_conn() as conn:
        for s in stocks:
            log(f"{s['name']} ({s['code']}) 데이터 수집 중 (PER/PBR, 수급, 시세, 토론실)...")
            save_stock(conn, s["code"], s["name"])

            per_pbr = fetch_per_pbr(s["code"])
            save_fundamentals_snapshot(
                conn, s["code"], today, s["price"], s["market_cap"],
                per_pbr["per"], per_pbr["pbr"], s["roe"],
            )

            supply_rows = fetch_supply_demand(s["code"], pages=SUPPLY_DEMAND_PAGES)
            save_supply_demand(conn, s["code"], supply_rows)

            price_rows = fetch_price_history(s["code"], pages=PRICE_HISTORY_PAGES)
            save_price_history(conn, s["code"], price_rows)

            posts = fetch_board_posts(s["code"], pages=BOARD_PAGES)
            posts = score_posts(posts)
            save_board_posts(conn, s["code"], posts)

    log("가치평가 + 수급 기반 종목 추천 계산 중...")
    fundamentals_df, supply_recent, board_df, price_df, name_map = _load_analysis_frames(stocks, today)
    rec_df = build_value_supply_table(fundamentals_df, supply_recent)
    market_cap_rank = {s["code"]: i + 1 for i, s in enumerate(stocks)}
    rec_df["market_cap_rank"] = rec_df["code"].map(market_cap_rank)

    log("커뮤니티 감성 vs 실제 수익률 상관관계 분석 중...")
    sentiment_return_df = build_sentiment_return_table(board_df, price_df, forward_days=1)
    corr_df = compute_correlation_by_stock(sentiment_return_df)
    corr_df = corr_df.assign(name=corr_df["code"].map(name_map))

    log("완료")
    return {
        "run_tag": run_tag,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "recommendations": _records(rec_df),
        "correlations": _records(corr_df),
    }


def run_pipeline_and_save(log) -> None:
    """pipeline_job.start(run_pipeline_and_save, pipeline_job.log)로 백그라운드 스레드에서 호출된다."""
    result = run_pipeline_live(log=log)
    path = os.path.join(DATA_DIR, "latest_run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def run_compare_and_save(stocks: list, days: int, log) -> None:
    """compare_job.start(run_compare_and_save, picked_stocks, window_days, compare_job.log)로 호출된다."""
    from stockanalyzer.analysis.compare import analyze_stock_window

    results = []
    for s in stocks:
        log(f"{s['name']} ({s['code']}) 분석 중... (최근 {days}일)")
        results.append(analyze_stock_window(s["code"], s["name"], days=days))

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "results": results,
    }
    path = os.path.join(DATA_DIR, "latest_compare.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_sector_and_save(sector_name: str, log) -> None:
    """sector_job.start(run_sector_and_save, sector_name, sector_job.log)로 호출된다."""
    from stockanalyzer.analysis.sector_recommend import analyze_sector

    result = analyze_sector(sector_name, log=log)
    result["timestamp"] = datetime.now().isoformat(timespec="seconds")
    path = os.path.join(DATA_DIR, "latest_sector.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def build_universe_and_save(log) -> None:
    """universe_job.start(build_universe_and_save, universe_job.log)로 호출된다."""
    from stockanalyzer.crawler.market_cap import fetch_all_listed_stocks

    stocks = fetch_all_listed_stocks(log=log)
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), "stocks": stocks}
    path = os.path.join(DATA_DIR, "stock_universe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
