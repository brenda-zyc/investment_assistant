#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import ssl
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Callable

import akshare as ak
import pandas as pd


# Some AkShare endpoints in this environment require relaxed SSL context.
ssl._create_default_https_context = ssl._create_unverified_context


@dataclass
class IndicatorSpec:
    """Configuration for one indicator fetch operation."""
    name: str
    fetcher: Callable[[], pd.DataFrame]


def _norm_date(series: pd.Series) -> pd.Series:
    """Normalize date-like series values into ISO date strings."""
    return pd.to_datetime(series, errors="coerce").dt.date.astype("string")


def _to_series(df: pd.DataFrame, date_col: str, value_col: str, name: str) -> pd.DataFrame:
    """Convert raw two-column source data into canonical [date, indicator] format."""
    # Data cleaning rule: coerce non-numeric values to NaN and deduplicate by date.
    out = df[[date_col, value_col]].copy()
    out.columns = ["date", name]
    out["date"] = _norm_date(out["date"])
    out[name] = pd.to_numeric(out[name], errors="coerce")
    out = out.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def fetch_gold() -> pd.DataFrame:
    """Fetch global gold futures history."""
    return _to_series(ak.futures_global_hist_em(symbol="GC00Y"), "日期", "最新价", "gold")


def fetch_silver() -> pd.DataFrame:
    """Fetch global silver futures history."""
    return _to_series(ak.futures_global_hist_em(symbol="SI00Y"), "日期", "最新价", "silver")


def fetch_oil() -> pd.DataFrame:
    """Fetch global crude oil futures history."""
    return _to_series(ak.futures_global_hist_em(symbol="CL00Y"), "日期", "最新价", "oil")


def fetch_usd_index() -> pd.DataFrame:
    """Fetch US Dollar Index history."""
    return _to_series(ak.index_global_hist_em(symbol="美元指数"), "日期", "最新价", "usd_index")


def fetch_us_10y_yield() -> pd.DataFrame:
    """Fetch US 10Y treasury yield history."""
    df = ak.bond_zh_us_rate(start_date="20100101")
    return _to_series(df, "日期", "美国国债收益率10年", "us_10y_yield")


def fetch_usd_cny() -> pd.DataFrame:
    """Fetch USD/CNY mid-point exchange rate history."""
    df = ak.macro_china_rmb()
    return _to_series(df, "日期", "美元/人民币_中间价", "usd_cny")


def fetch_china_pmi() -> pd.DataFrame:
    """Fetch China PMI history and normalize month labels into date values."""
    df = ak.macro_china_pmi().copy()
    # Source format: "2026年01月份"
    def parse_month(value: str) -> str | None:
        """Convert PMI month text into canonical YYYY-MM-01 format."""
        m = re.match(r"^(\d{4})年(\d{2})月份$", str(value))
        if not m:
            return None
        return f"{m.group(1)}-{m.group(2)}-01"

    df["日期"] = df["月份"].apply(parse_month)
    return _to_series(df, "日期", "制造业-指数", "china_pmi")


def fetch_shanghai_pe() -> pd.DataFrame:
    """Fetch Shanghai Composite valuation history (PE)."""
    df = ak.stock_market_pe_lg(symbol="上证")
    return _to_series(df, "日期", "平均市盈率", "shanghai_composite_pe")


def fetch_csi300_pe() -> pd.DataFrame:
    """Fetch CSI 300 valuation history (rolling PE)."""
    df = ak.stock_index_pe_lg(symbol="沪深300")
    # Use rolling PE (TTM-like) as the primary valuation metric.
    return _to_series(df, "日期", "滚动市盈率", "csi300_pe")


def fetch_chinext_pe() -> pd.DataFrame:
    """Fetch ChiNext valuation history (PE)."""
    df = ak.stock_market_pe_lg(symbol="创业板")
    return _to_series(df, "日期", "平均市盈率", "chinext_pe")


def fetch_star_market_pe() -> pd.DataFrame:
    """Fetch STAR Market valuation history (PE)."""
    df = ak.stock_market_pe_lg(symbol="科创板")
    return _to_series(df, "日期", "平均市盈率", "star_market_pe")


def _fetch_hk_index_pe(symbol_candidates: list[str], target_col: str) -> pd.DataFrame:
    """Fetch Hong Kong index PE using candidate symbols until one succeeds."""
    # API assumption: symbol support can vary across providers and time.
    for symbol in symbol_candidates:
        try:
            df = ak.stock_hk_valuation_baidu(
                symbol=symbol, indicator="市盈率(TTM)", period="近三年"
            )
            if not df.empty and {"date", "value"}.issubset(df.columns):
                tmp = df.rename(columns={"date": "日期", "value": "值"})
                return _to_series(tmp, "日期", "值", target_col)
        except Exception:
            continue
    return pd.DataFrame(columns=["date", target_col])


def fetch_hang_seng_pe() -> pd.DataFrame:
    """Fetch Hang Seng Index valuation history (PE)."""
    return _fetch_hk_index_pe(["HSI", "800000", "02800"], "hang_seng_pe")


def fetch_hang_seng_tech_pe() -> pd.DataFrame:
    """Fetch Hang Seng Tech Index valuation history (PE)."""
    return _fetch_hk_index_pe(["HSTECH", "800700", "03033"], "hang_seng_tech_pe")


def merge_on_date(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Outer-join all indicator frames by date."""
    if not frames:
        return pd.DataFrame(columns=["date"])
    merged = reduce(lambda left, right: left.merge(right, on="date", how="outer"), frames)
    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


def save_to_sqlite(df: pd.DataFrame, db_path: Path, table: str) -> None:
    """Persist merged indicator dataset into a SQLite table."""
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)


def _load_fallback_history(db_path: Path, required_cols: list[str]) -> pd.DataFrame:
    """Load compatible historical data from existing macro tables as fallback."""
    candidates = ["macro_indicators_step2", "macro_indicators", "macro_indicators_step1"]
    with sqlite3.connect(db_path) as conn:
        for table_name in candidates:
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            except Exception:
                continue
            if df.empty or "date" not in df.columns:
                continue

            # Backward-compatible rename from older schema.
            if "shanghai_pe" in df.columns and "shanghai_composite_pe" not in df.columns:
                df = df.rename(columns={"shanghai_pe": "shanghai_composite_pe"})

            for col in required_cols:
                if col not in df.columns:
                    df[col] = pd.NA

            ordered_cols = ["date"] + required_cols
            df = df[ordered_cols].copy()
            df["date"] = _norm_date(df["date"])
            df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")
            df = df.sort_values("date").reset_index(drop=True)
            if not df.empty:
                print(f"[WARN] Using fallback history from existing table: {table_name}")
                return df

    return pd.DataFrame(columns=["date"] + required_cols)


def run(step: int, db_path: Path, table: str) -> pd.DataFrame:
    """Run Step 1/2 pipeline and write merged indicators to SQLite."""
    core_specs = [
        IndicatorSpec("gold", fetch_gold),
        IndicatorSpec("silver", fetch_silver),
        IndicatorSpec("oil", fetch_oil),
        IndicatorSpec("usd_index", fetch_usd_index),
        IndicatorSpec("us_10y_yield", fetch_us_10y_yield),
    ]

    ext_specs = [
        IndicatorSpec("usd_cny", fetch_usd_cny),
        IndicatorSpec("china_pmi", fetch_china_pmi),
        IndicatorSpec("shanghai_composite_pe", fetch_shanghai_pe),
        IndicatorSpec("csi300_pe", fetch_csi300_pe),
        IndicatorSpec("chinext_pe", fetch_chinext_pe),
        IndicatorSpec("star_market_pe", fetch_star_market_pe),
        IndicatorSpec("hang_seng_pe", fetch_hang_seng_pe),
        IndicatorSpec("hang_seng_tech_pe", fetch_hang_seng_tech_pe),
    ]

    specs = core_specs if step == 1 else core_specs + ext_specs
    frames: list[pd.DataFrame] = []

    for spec in specs:
        print(f"[INFO] Fetching {spec.name} ...")
        try:
            frame = spec.fetcher()
        except Exception as exc:
            # Keep pipeline resilient: one failed source must not block all outputs.
            print(f"[WARN] {spec.name} fetch failed: {exc}")
            frame = pd.DataFrame(columns=["date", spec.name])
        frames.append(frame)
        print(f"[INFO] {spec.name}: {len(frame)} rows")

    merged = merge_on_date(frames)
    required_cols = [spec.name for spec in specs]
    if merged.empty:
        merged = _load_fallback_history(db_path=db_path, required_cols=required_cols)
    # TODO: add per-source freshness timestamp for observability.
    save_to_sqlite(merged, db_path, table)
    return merged


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for macro indicator ingestion job."""
    parser = argparse.ArgumentParser(
        description="Fetch macro/market indicators with AkShare and save merged table to SQLite."
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2],
        default=2,
        help="1: core 5 indicators; 2: extended indicators (default).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("investment.db"),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--table",
        type=str,
        default="macro_indicators",
        help="SQLite table name.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=5,
        help="Print last N rows after save.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for CLI execution."""
    args = parse_args()
    merged = run(step=args.step, db_path=args.db, table=args.table)
    print(
        f"[DONE] Saved {len(merged)} merged rows to {args.db.resolve()}::{args.table} "
        f"with {len(merged.columns) - 1} indicators."
    )
    if args.tail > 0 and not merged.empty:
        print(merged.tail(args.tail).to_string(index=False))


if __name__ == "__main__":
    main()
