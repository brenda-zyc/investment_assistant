import sqlite3
import re
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "investment.db"


def _validate_table_name(table_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError("Invalid table name")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_prices (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            PRIMARY KEY (symbol, trade_date)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_reports (
            symbol TEXT NOT NULL,
            report_year INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            revenue REAL,
            net_profit REAL,
            roe REAL,
            debt_ratio REAL,
            PRIMARY KEY (symbol, report_year)
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_stock_prices(symbol: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO stock_prices (
            symbol, trade_date, open, close, high, low, volume, amount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, trade_date) DO UPDATE SET
            open=excluded.open,
            close=excluded.close,
            high=excluded.high,
            low=excluded.low,
            volume=excluded.volume,
            amount=excluded.amount
        """,
        [
            (
                symbol,
                row["trade_date"],
                row.get("open"),
                row.get("close"),
                row.get("high"),
                row.get("low"),
                row.get("volume"),
                row.get("amount"),
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def upsert_financial_reports(symbol: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO financial_reports (
            symbol, report_year, report_date, revenue, net_profit, roe, debt_ratio
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, report_year) DO UPDATE SET
            report_date=excluded.report_date,
            revenue=excluded.revenue,
            net_profit=excluded.net_profit,
            roe=excluded.roe,
            debt_ratio=excluded.debt_ratio
        """,
        [
            (
                symbol,
                row["report_year"],
                row["report_date"],
                row.get("revenue"),
                row.get("net_profit"),
                row.get("roe"),
                row.get("debt_ratio"),
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def fetch_stock_prices(symbol: str) -> list[dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT symbol, trade_date, open, close, high, low, volume, amount
        FROM stock_prices
        WHERE symbol = ?
        ORDER BY trade_date DESC
        """,
        (symbol,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def fetch_financial_reports(symbol: str) -> list[dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT symbol, report_year, report_date, revenue, net_profit, roe, debt_ratio
        FROM financial_reports
        WHERE symbol = ?
        ORDER BY report_year DESC
        """,
        (symbol,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def fetch_macro_indicators(table_name: str, limit: int = 30) -> list[dict[str, Any]]:
    _validate_table_name(table_name)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    )
    if cur.fetchone() is None:
        conn.close()
        return []

    cur.execute(f"SELECT * FROM {table_name} ORDER BY date DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def fetch_macro_indicators_all(table_name: str) -> list[dict[str, Any]]:
    _validate_table_name(table_name)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    )
    if cur.fetchone() is None:
        conn.close()
        return []

    cur.execute(f"SELECT * FROM {table_name} ORDER BY date DESC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
