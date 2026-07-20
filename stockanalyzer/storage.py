"""크롤링 결과를 누적 저장하는 SQLite 저장소.
매 실행마다 기존 데이터에 새 데이터를 추가(UPSERT)하므로, 반복 실행할수록 과거 데이터가 쌓인다."""
import sqlite3
from contextlib import contextmanager

from stockanalyzer.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS fundamentals_snapshot (
    code TEXT,
    snapshot_date TEXT,
    price REAL,
    market_cap REAL,
    per REAL,
    pbr REAL,
    roe REAL,
    PRIMARY KEY (code, snapshot_date)
);

CREATE TABLE IF NOT EXISTS supply_demand (
    code TEXT,
    date TEXT,
    close REAL,
    inst_net_qty REAL,
    foreign_net_qty REAL,
    foreign_ratio REAL,
    inst_net_value_est REAL,
    foreign_net_value_est REAL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS price_history (
    code TEXT,
    date TEXT,
    close REAL,
    open REAL,
    high REAL,
    low REAL,
    volume REAL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS board_posts (
    code TEXT,
    date TEXT,
    title TEXT,
    writer TEXT,
    views REAL,
    likes REAL,
    dislikes REAL,
    sentiment_score INTEGER,
    sentiment_label TEXT,
    PRIMARY KEY (code, date, title, writer)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_stock(conn, code: str, name: str):
    conn.execute(
        "INSERT INTO stocks (code, name) VALUES (?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name",
        (code, name),
    )


def save_fundamentals_snapshot(conn, code: str, snapshot_date: str, price, market_cap, per, pbr, roe):
    conn.execute(
        """INSERT INTO fundamentals_snapshot
           (code, snapshot_date, price, market_cap, per, pbr, roe)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(code, snapshot_date) DO UPDATE SET
              price=excluded.price, market_cap=excluded.market_cap,
              per=excluded.per, pbr=excluded.pbr, roe=excluded.roe""",
        (code, snapshot_date, price, market_cap, per, pbr, roe),
    )


def save_supply_demand(conn, code: str, rows: list):
    for r in rows:
        conn.execute(
            """INSERT INTO supply_demand
               (code, date, close, inst_net_qty, foreign_net_qty, foreign_ratio,
                inst_net_value_est, foreign_net_value_est)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, date) DO UPDATE SET
                  close=excluded.close, inst_net_qty=excluded.inst_net_qty,
                  foreign_net_qty=excluded.foreign_net_qty, foreign_ratio=excluded.foreign_ratio,
                  inst_net_value_est=excluded.inst_net_value_est,
                  foreign_net_value_est=excluded.foreign_net_value_est""",
            (
                code, r["date"], r["close"], r["inst_net_qty"], r["foreign_net_qty"],
                r["foreign_ratio"], r["inst_net_value_est"], r["foreign_net_value_est"],
            ),
        )


def save_price_history(conn, code: str, rows: list):
    for r in rows:
        conn.execute(
            """INSERT INTO price_history (code, date, close, open, high, low, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, date) DO UPDATE SET
                  close=excluded.close, open=excluded.open, high=excluded.high,
                  low=excluded.low, volume=excluded.volume""",
            (code, r["date"], r["close"], r["open"], r["high"], r["low"], r["volume"]),
        )


def save_board_posts(conn, code: str, posts: list):
    for p in posts:
        conn.execute(
            """INSERT INTO board_posts
               (code, date, title, writer, views, likes, dislikes, sentiment_score, sentiment_label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, date, title, writer) DO NOTHING""",
            (
                code, p["date"], p["title"], p["writer"], p["views"], p["likes"],
                p["dislikes"], p.get("sentiment_score", 0), p.get("sentiment_label", "중립"),
            ),
        )
