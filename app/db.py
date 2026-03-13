import sqlite3
import re
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "investment.db"
SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MS = 5000


def _validate_table_name(table_name: str) -> None:
    """Validate dynamic table name to prevent unsafe SQL interpolation."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError("Invalid table name")


def get_conn() -> sqlite3.Connection:
    """Create a SQLite connection with dict-like row access."""
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    # Keep write contention tolerable when bounded watchlist fan-out persists caches concurrently.
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def init_db() -> None:
    """Initialize core application tables if they do not exist."""
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS industry_prices (
            industry TEXT NOT NULL,
            indicator TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            value REAL,
            source TEXT,
            PRIMARY KEY (indicator, trade_date)
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_stock_prices(symbol: str, rows: list[dict[str, Any]]) -> None:
    """Insert or update stock daily price rows for one symbol."""
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
    """Insert or update normalized financial rows for one symbol."""
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
    """Fetch stored price history ordered by most recent trade date."""
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
    """Fetch stored financial rows ordered by latest report year."""
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
    """Fetch latest macro rows from a validated table name."""
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
    """Fetch full macro history from a validated table name."""
    # TODO: support streaming/chunked reads if dataset grows significantly.
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


def upsert_industry_prices(rows: list[dict[str, Any]]) -> None:
    """Insert or update industry indicator historical points."""
    if not rows:
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO industry_prices (industry, indicator, trade_date, value, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(indicator, trade_date) DO UPDATE SET
            industry=excluded.industry,
            value=excluded.value,
            source=excluded.source
        """,
        [
            (
                row["industry"],
                row["indicator"],
                row["trade_date"],
                row.get("value"),
                row.get("source"),
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def fetch_industry_prices(indicator: str | None = None) -> list[dict[str, Any]]:
    """Fetch stored industry historical points sorted by indicator/date."""
    conn = get_conn()
    cur = conn.cursor()

    if indicator:
        cur.execute(
            """
            SELECT industry, indicator, trade_date, value, source
            FROM industry_prices
            WHERE indicator = ?
            ORDER BY indicator ASC, trade_date ASC
            """,
            (indicator,),
        )
    else:
        cur.execute(
            """
            SELECT industry, indicator, trade_date, value, source
            FROM industry_prices
            ORDER BY indicator ASC, trade_date ASC
            """
        )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
