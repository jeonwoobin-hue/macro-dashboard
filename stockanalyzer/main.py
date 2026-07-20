"""전체 파이프라인 실행 스크립트.
1) 네이버 금융에서 실시간 크롤링 (시가총액 상위 종목, PER/PBR, 수급, 과거 시세, 종목토론실)
2) SQLite에 누적 저장 (실행할수록 과거 데이터가 쌓임)
3) 가치평가(PER/PBR) + 수급 기반 종목 추천/그룹화
4) 커뮤니티 감성 vs 실제 수익률 상관관계 분석
5) 차트 + 마크다운 리포트 생성
"""
import json
import sys
from datetime import datetime

import pandas as pd

from stockanalyzer.config import (
    TOP_N_STOCKS, SUPPLY_DEMAND_PAGES, PRICE_HISTORY_PAGES, BOARD_PAGES,
)
from stockanalyzer.crawler.market_cap import fetch_top_market_cap
from stockanalyzer.crawler.fundamentals import fetch_per_pbr
from stockanalyzer.crawler.supply_demand import fetch_supply_demand
from stockanalyzer.crawler.price import fetch_price_history
from stockanalyzer.crawler.community import fetch_board_posts
from stockanalyzer.analysis.sentiment import score_posts
from stockanalyzer.analysis.recommend import build_value_supply_table
from stockanalyzer.analysis.correlate import build_sentiment_return_table, compute_correlation_by_stock
from stockanalyzer.storage import (
    init_db, get_conn, save_stock, save_fundamentals_snapshot,
    save_supply_demand, save_price_history, save_board_posts,
)
from stockanalyzer import report

SUPPLY_WINDOW_DAYS = 20  # 최근 N거래일 수급 합산 기준


def _records(df: pd.DataFrame) -> list:
    """DataFrame을 JSON 직렬화 가능한 dict 리스트로 변환한다.
    df.to_dict()는 NaN을 float('nan')으로 남겨 웹에서 'nan' 문자열로 노출되므로,
    pandas의 to_json 경로를 거쳐 NaN을 null(None)로 정규화한다."""
    return json.loads(df.to_json(orient="records"))


def load_analysis_frames(stocks: list, today: str):
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


def run_pipeline(log=print) -> dict:
    """크롤링부터 리포트 생성까지 전체 파이프라인을 실행하고 결과를 dict로 반환한다.
    log: 진행상황을 전달받을 콜백(기본은 print). 웹 서버에서는 상태 저장 함수를 넘겨 진행률을 노출한다."""
    today = datetime.now().strftime("%Y-%m-%d")
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    init_db()

    log(f"[1/5] 시가총액 상위 {TOP_N_STOCKS}개 종목 조회 중...")
    stocks = fetch_top_market_cap(TOP_N_STOCKS)
    for s in stocks:
        log(f"   - {s['name']} ({s['code']})")

    with get_conn() as conn:
        for s in stocks:
            log(f"[2/5] {s['name']} 데이터 수집 중 (PER/PBR, 수급, 시세, 토론실)...")
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

    log("[3/5] 가치평가(PER/PBR) + 수급 기반 종목 추천 계산 중...")
    fundamentals_df, supply_recent, board_df, price_df, name_map = load_analysis_frames(stocks, today)
    rec_df = build_value_supply_table(fundamentals_df, supply_recent)
    market_cap_rank = {s["code"]: i + 1 for i, s in enumerate(stocks)}
    rec_df["market_cap_rank"] = rec_df["code"].map(market_cap_rank)

    log("[4/5] 커뮤니티 감성 vs 실제 수익률 상관관계 분석 중...")
    sentiment_return_df = build_sentiment_return_table(board_df, price_df, forward_days=1)
    corr_df = compute_correlation_by_stock(sentiment_return_df)
    corr_df = corr_df.assign(name=corr_df["code"].map(name_map))

    log("[5/5] 차트 및 리포트 생성 중...")
    chart_paths = [
        report.plot_recommendation_scatter(rec_df, run_tag),
        report.plot_total_score_bar(rec_df, run_tag),
        report.plot_sentiment_correlation_bar(corr_df, name_map, run_tag),
    ]
    report_path = report.write_markdown_report(rec_df, corr_df, name_map, chart_paths, run_tag)

    log(f"완료! 리포트: {report_path}")

    return {
        "run_tag": run_tag,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "recommendations": _records(rec_df),
        "correlations": _records(corr_df),
        "chart_files": [p.split("\\")[-1].split("/")[-1] for p in chart_paths if p],
        "report_path": report_path,
    }


if __name__ == "__main__":
    result = run_pipeline()
    print(f"\n분석된 종목 수: {len(result['recommendations'])}")
    sys.exit(0)
