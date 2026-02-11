from __future__ import annotations

import datetime as dt
import logging
import socket
import time
from typing import Any

import akshare as ak
import pandas as pd

from app.data_service import _call_with_resilience, _find_col, to_date_str, to_float

logger = logging.getLogger(__name__)

_HOST_RESOLVE_OK_CACHE: dict[str, float] = {}

INDUSTRY_INDICATOR_SPECS: list[dict[str, str]] = [
    {
        "industry": "Energy",
        "indicator_key": "brent_oil",
        "indicator": "brent_oil",
        "global_symbols": "B00Y,CL00Y",
        "sina_contract": "SC0",
        "basis_var": "SC",
    },
    {
        "industry": "Energy",
        "indicator_key": "thermal_coal",
        "indicator": "thermal_coal",
        "sina_contract": "ZC0",
        "basis_var": "ZC",
    },
    {
        "industry": "New Energy & Metals",
        "indicator_key": "lithium_carbonate",
        "indicator": "lithium_carbonate",
        "sina_contract": "LC0",
        "basis_var": "LC",
    },
    {
        "industry": "New Energy & Metals",
        "indicator_key": "copper_price",
        "indicator": "copper_price",
        "sina_contract": "CU0",
        "basis_var": "CU",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "rebar_price",
        "indicator": "rebar_price",
        "sina_contract": "RB0",
        "basis_var": "RB",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "iron_ore_price",
        "indicator": "iron_ore_price",
        "sina_contract": "I0",
        "basis_var": "I",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "cement_price",
        "indicator": "cement_price",
        "special_source": "construction_index",
        "basis_var": "ZC",
    },
    {
        "industry": "Solar",
        "indicator_key": "silicon_wafer_price",
        "indicator": "silicon_wafer_price",
        "sina_contract": "SI0",
        "basis_var": "SI",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "pork_price",
        "indicator": "pork_price",
        "special_source": "soozhu_pork",
        "sina_contract": "LH0",
        "basis_var": "LH",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "corn_price",
        "indicator": "corn_price",
        "special_source": "soozhu_corn",
        "sina_contract": "C0",
        "basis_var": "C",
    },
    {
        "industry": "Chemicals",
        "indicator_key": "methanol_price",
        "indicator": "methanol_price",
        "sina_contract": "MA0",
        "basis_var": "MA",
    },
    {
        "industry": "Chemicals",
        "indicator_key": "rubber_price",
        "indicator": "rubber_price",
        "sina_contract": "RU0",
        "basis_var": "RU",
    },
]


def get_industry_indicator_specs() -> list[dict[str, str]]:
    """Return industry indicator catalog used by industry cycle API."""
    return [dict(item) for item in INDUSTRY_INDICATOR_SPECS]


def _dedupe_points(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Deduplicate points by date and return ascending date order."""
    bucket: dict[str, float] = {}
    for date_text, value in points:
        bucket[date_text] = value
    return sorted(bucket.items(), key=lambda item: item[0])


def _normalize_history_frame(df: pd.DataFrame, date_col: str, value_col: str) -> list[tuple[str, float]]:
    """Normalize dataframe to ascending [(date, value)] points."""
    if df is None or df.empty:
        return []

    points: list[tuple[str, float]] = []
    for _, row in df.iterrows():
        date_text = to_date_str(row.get(date_col))
        value = to_float(row.get(value_col))
        # Data cleaning rule: keep valid date + numeric value only.
        if not date_text or value is None:
            continue
        points.append((date_text, value))
    return _dedupe_points(points)


def _is_host_resolvable(host: str) -> bool:
    """Return whether host DNS resolves in current runtime environment."""
    # Failure is not cached to avoid stale-DNS false negatives after network recovery.
    now = time.time()
    cache_ttl_seconds = 60
    last_ok_ts = _HOST_RESOLVE_OK_CACHE.get(host)
    if last_ok_ts and (now - last_ok_ts) <= cache_ttl_seconds:
        return True
    try:
        socket.gethostbyname(host)
        _HOST_RESOLVE_OK_CACHE[host] = now
        return True
    except Exception:
        return False


def _fetch_futures_basis_series(var_symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch one commodity spot series from futures basis endpoint by contract symbol."""
    if not _is_host_resolvable("www.100ppi.com"):
        logger.warning("industry_cycles host_unreachable=www.100ppi.com skip_symbol=%s", var_symbol)
        return []
    df = _call_with_resilience(
        ak.futures_spot_price_daily,
        start_day=start_date,
        end_day=end_date,
        vars_list=[var_symbol],
    )
    if df is None or df.empty:
        return []
    if not {"var", "sp", "date"}.issubset(set(df.columns)):
        return []
    sliced = df[df["var"].astype(str) == var_symbol][["date", "sp"]].copy()
    return _normalize_history_frame(sliced, "date", "sp")


def _fetch_futures_global_hist_series(
    symbol_candidates: list[str],
    start_date: str,
    end_date: str,
) -> tuple[list[tuple[str, float]], str]:
    """Fetch global futures history from candidate symbols and return first non-empty result."""
    start_text = to_date_str(start_date)
    end_text = to_date_str(end_date)
    for symbol in symbol_candidates:
        try:
            df = _call_with_resilience(ak.futures_global_hist_em, symbol=symbol)
        except Exception as exc:
            logger.warning("industry_cycles global_hist failed symbol=%s err=%s", symbol, exc)
            continue
        if df is None or df.empty:
            continue
        cols = [str(c) for c in df.columns]
        date_col = _find_col(cols, ["日期", "date"])
        price_col = _find_col(cols, ["最新价", "收盘", "close"])
        if not date_col or not price_col:
            continue
        points = _normalize_history_frame(df, date_col, price_col)
        if start_text and end_text:
            points = [point for point in points if start_text <= point[0] <= end_text]
        if points:
            return points, symbol
    return [], ""


def _fetch_futures_daily_sina_series(contract_symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch one futures daily close series from Sina."""
    df = _call_with_resilience(ak.futures_zh_daily_sina, symbol=contract_symbol)
    if df is None or df.empty:
        return []
    cols = [str(c) for c in df.columns]
    date_col = _find_col(cols, ["date", "日期"])
    close_col = _find_col(cols, ["close", "收盘", "最新价"])
    if not date_col or not close_col:
        return []
    points = _normalize_history_frame(df, date_col, close_col)
    if not points:
        return []
    start_text = to_date_str(start_date)
    end_text = to_date_str(end_date)
    if not start_text or not end_text:
        return points
    return [point for point in points if start_text <= point[0] <= end_text]


def _fetch_construction_index_series() -> list[tuple[str, float]]:
    """Fetch construction-price index history."""
    df = _call_with_resilience(ak.macro_china_construction_price_index)
    if df is None or df.empty:
        return []
    return _normalize_history_frame(df, "日期", "最新值")


def _fetch_pork_spot_series() -> list[tuple[str, float]]:
    """Fetch pork spot price history from Soozhu."""
    df = _call_with_resilience(ak.spot_hog_lean_price_soozhu)
    if df is None or df.empty:
        return []
    return _normalize_history_frame(df, "日期", "价格")


def _fetch_corn_spot_series() -> list[tuple[str, float]]:
    """Fetch corn spot price history from Soozhu."""
    df = _call_with_resilience(ak.spot_corn_price_soozhu)
    if df is None or df.empty:
        return []
    return _normalize_history_frame(df, "日期", "价格")


def _today_yyyymmdd() -> str:
    """Return today's date in YYYYMMDD format."""
    return dt.date.today().strftime("%Y%m%d")


def _days_ago_yyyymmdd(days: int) -> str:
    """Return date string offset by N days."""
    return (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")


def _fetch_single_industry_series(spec: dict[str, str], start_date: str, end_date: str) -> tuple[list[tuple[str, float]], str]:
    """Fetch one indicator series using priority-ordered source fallbacks."""
    indicator_key = spec["indicator_key"]

    global_symbols_text = str(spec.get("global_symbols") or "").strip()
    if global_symbols_text:
        candidates = [item.strip() for item in global_symbols_text.split(",") if item.strip()]
        points, chosen_symbol = _fetch_futures_global_hist_series(candidates, start_date, end_date)
        if points:
            return points, f"futures_global_hist_em:{chosen_symbol}"

    special_source = str(spec.get("special_source") or "").strip()
    if special_source == "construction_index":
        points = _fetch_construction_index_series()
        if points:
            return points, "macro_china_construction_price_index"
    if special_source == "soozhu_pork":
        points = _fetch_pork_spot_series()
        if points:
            return points, "spot_hog_lean_price_soozhu"
    if special_source == "soozhu_corn":
        points = _fetch_corn_spot_series()
        if points:
            return points, "spot_corn_price_soozhu"

    sina_contract = str(spec.get("sina_contract") or "").strip()
    if sina_contract:
        try:
            points = _fetch_futures_daily_sina_series(sina_contract, start_date, end_date)
            if points:
                return points, f"futures_zh_daily_sina:{sina_contract}"
        except Exception as exc:
            logger.warning("industry_cycles sina source failed indicator=%s err=%s", indicator_key, exc)

    basis_var = str(spec.get("basis_var") or "").strip()
    if basis_var:
        start_text = to_date_str(start_date)
        end_text = to_date_str(end_date)
        if start_text and end_text:
            start_dt = pd.to_datetime(start_text)
            end_dt = pd.to_datetime(end_text)
            # Avoid very slow long-range basis scraping in request path.
            if (end_dt - start_dt).days > 220:
                return [], ""
        try:
            points = _fetch_futures_basis_series(basis_var, start_date, end_date)
            if points:
                return points, f"futures_spot_price_daily:{basis_var}"
        except Exception as exc:
            logger.warning("industry_cycles basis source failed indicator=%s err=%s", indicator_key, exc)
    return [], ""


def fetch_industry_price_rows(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    """Fetch industry cycle rows normalized for SQLite upsert."""
    start_date = start_date or _days_ago_yyyymmdd(120)
    end_date = end_date or _today_yyyymmdd()
    out: list[dict[str, Any]] = []

    for spec in INDUSTRY_INDICATOR_SPECS:
        points, source = _fetch_single_industry_series(spec, start_date=start_date, end_date=end_date)
        logger.info(
            "industry_cycles indicator=%s points=%d source=%s",
            spec["indicator_key"],
            len(points),
            source or "none",
        )
        for date_text, value in points:
            out.append(
                {
                    "industry": spec["industry"],
                    "indicator": spec["indicator_key"],
                    "trade_date": date_text,
                    "value": value,
                    "source": source,
                }
            )
    # TODO: persist per-source refresh diagnostics for UI observability.
    return out
