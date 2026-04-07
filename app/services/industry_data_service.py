from __future__ import annotations

import datetime as dt
from io import StringIO
import logging
import re
import socket
import time
import warnings
from typing import Any

import akshare as ak
import pandas as pd
import requests

from app.services.common import _call_with_resilience, _find_col, to_date_str, to_float

logger = logging.getLogger(__name__)

_HOST_RESOLVE_OK_CACHE: dict[str, float] = {}
_TREASURY_CURVE_TABLE_CACHE: dict[str, tuple[float, list[pd.DataFrame]]] = {}

# API assumption: these hosts are the critical availability gates for each upstream family.
_SOURCE_HOSTS: dict[str, list[str]] = {
    "futures_global_hist_em": ["push2his.eastmoney.com"],
    "futures_zh_daily_sina": ["stock2.finance.sina.com.cn"],
    "macro_china_construction_price_index": ["datacenter-web.eastmoney.com"],
    "spot_hog_lean_price_soozhu": ["www.soozhu.com"],
    "spot_corn_price_soozhu": ["www.soozhu.com"],
    "futures_spot_price_daily": ["www.100ppi.com"],
    "forex_hist_em": ["push2his.eastmoney.com"],
    "index_global_hist_em": ["push2his.eastmoney.com"],
    "us_treasury_curve": ["home.treasury.gov"],
    "zhaomei_water_coal": ["m.zhaomei.com"],
}

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

EXTERNAL_DATA_SPECS: list[dict[str, str]] = [
    {
        "indicator_key": "comex_silver",
        "indicator": "银价（COMEX白银）",
        "fetch_kind": "global_future",
        "symbol": "SI00Y",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/globalfuture/SI00Y.html?jump_to_web=true",
        "note": "直接抓取 COMEX 白银历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "comex_gold",
        "indicator": "金价（COMEX黄金）",
        "fetch_kind": "global_future",
        "symbol": "GC00Y",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/globalfuture/GC00Y.html?jump_to_web=true",
        "note": "直接抓取 COMEX 黄金历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "gold_td",
        "indicator": "黄金T+D",
        "fetch_kind": "global_future",
        "symbol": "AUTD",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/globalfuture/AUTD.html?jump_to_web=true",
        "note": "直接抓取黄金 T+D 历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "nymex_oil",
        "indicator": "油价（NYMEX原油）",
        "fetch_kind": "global_future",
        "symbol": "CL00Y",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/globalfuture/CL00Y.html?jump_to_web=true",
        "note": "直接抓取 NYMEX 原油历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "eur_cnh",
        "indicator": "欧元汇率（欧元兑离岸人民币）",
        "fetch_kind": "forex_hist",
        "symbol": "EURCNH",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/forex/EURCNH.html?jump_to_web=true",
        "note": "为保持与美元项一致，统一使用东方财富外汇历史数据抓取。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "usd_cnh",
        "indicator": "美元汇率（美元兑离岸人民币）",
        "fetch_kind": "forex_hist",
        "symbol": "USDCNH",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/forex/USDCNH.html?jump_to_web=true",
        "note": "直接抓取美元兑离岸人民币历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "dollar_index",
        "indicator": "美元指数",
        "fetch_kind": "global_index",
        "symbol": "美元指数",
        "source": "东方财富",
        "source_url": "https://quote.eastmoney.com/gb/zsUDI.html?jump_to_web=true",
        "note": "直接抓取全球指数中的美元指数历史行情最新值。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "us_treasury_6m",
        "indicator": "美债半年",
        "fetch_kind": "us_treasury_curve",
        "column": "6 Mo",
        "source": "U.S. Treasury",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "note": "使用美国财政部官方日度收益率曲线，替代英为财情页面抓取。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "us_treasury_10y",
        "indicator": "美债10年",
        "fetch_kind": "us_treasury_curve",
        "column": "10 Yr",
        "source": "U.S. Treasury",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "note": "使用美国财政部官方日度收益率曲线，替代英为财情页面抓取。",
        "status_on_success": "ok",
    },
    {
        "indicator_key": "thermal_coal_5500k",
        "indicator": "煤炭5500K：动力煤",
        "fetch_kind": "basis_proxy",
        "basis_var": "ZC",
        "source": "100ppi（代理）",
        "source_url": "https://www.100ppi.com/sf/",
        "note": "原中国煤炭市场网页面不稳定，暂用 100ppi 动力煤现货代理值。",
        "status_on_success": "proxy",
    },
    {
        "indicator_key": "cement_coal_5500k",
        "indicator": "煤炭5500K：水泥煤",
        "fetch_kind": "zhaomei_water_coal",
        "source": "找煤网",
        "source_url": "https://m.zhaomei.com/",
        "note": "按找煤网首页公开水泥煤价格抓取。",
        "status_on_success": "ok",
    },
]


def get_industry_indicator_specs() -> list[dict[str, str]]:
    """Return industry indicator catalog used by industry cycle API."""
    return [dict(item) for item in INDUSTRY_INDICATOR_SPECS]


def get_external_data_specs() -> list[dict[str, str]]:
    """Return external indicator catalog used by the industry-side reference module."""
    return [dict(item) for item in EXTERNAL_DATA_SPECS]


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


def _filter_points_to_window(
    points: list[tuple[str, float]],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[tuple[str, float]]:
    """Filter normalized points into a requested ISO-date window."""
    start_text = to_date_str(start_date)
    end_text = to_date_str(end_date)
    if not start_text or not end_text:
        return points
    return [point for point in points if start_text <= point[0] <= end_text]


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


def _host_status_text(host: str) -> str:
    """Return host DNS health label."""
    return "dns_ok" if _is_host_resolvable(host) else "dns_failed"


def _resolve_source_hosts(source_name: str) -> list[str]:
    """Return configured host list for a source name."""
    return list(_SOURCE_HOSTS.get(source_name, []))


def _build_dns_snapshot() -> dict[str, str]:
    """Collect one-shot DNS status snapshot for all known source hosts."""
    hosts = sorted({host for host_list in _SOURCE_HOSTS.values() for host in host_list})
    return {host: _host_status_text(host) for host in hosts}


def _expected_hosts_for_spec(spec: dict[str, str]) -> list[str]:
    """Infer candidate hosts for an indicator based on configured source fallbacks."""
    hosts: set[str] = set()
    if str(spec.get("global_symbols") or "").strip():
        hosts.update(_resolve_source_hosts("futures_global_hist_em"))
    special_source = str(spec.get("special_source") or "").strip()
    if special_source == "construction_index":
        hosts.update(_resolve_source_hosts("macro_china_construction_price_index"))
    if special_source == "soozhu_pork":
        hosts.update(_resolve_source_hosts("spot_hog_lean_price_soozhu"))
    if special_source == "soozhu_corn":
        hosts.update(_resolve_source_hosts("spot_corn_price_soozhu"))
    if str(spec.get("sina_contract") or "").strip():
        hosts.update(_resolve_source_hosts("futures_zh_daily_sina"))
    if str(spec.get("basis_var") or "").strip():
        hosts.update(_resolve_source_hosts("futures_spot_price_daily"))
    return sorted(hosts)


def _expected_hosts_for_external_spec(spec: dict[str, str]) -> list[str]:
    """Infer candidate hosts for an external indicator based on its configured fetch strategy."""
    fetch_kind = str(spec.get("fetch_kind") or "").strip()
    if fetch_kind == "global_future":
        return _resolve_source_hosts("futures_global_hist_em")
    if fetch_kind == "forex_hist":
        return _resolve_source_hosts("forex_hist_em")
    if fetch_kind == "global_index":
        return _resolve_source_hosts("index_global_hist_em")
    if fetch_kind == "us_treasury_curve":
        return _resolve_source_hosts("us_treasury_curve")
    if fetch_kind == "zhaomei_water_coal":
        return _resolve_source_hosts("zhaomei_water_coal")
    if fetch_kind == "basis_proxy":
        return _resolve_source_hosts("futures_spot_price_daily")
    return []


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


def _fetch_forex_hist_series(symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch one forex history series from Eastmoney and return latest-close points."""
    df = _call_with_resilience(ak.forex_hist_em, symbol=symbol)
    if df is None or df.empty:
        return []
    points = _normalize_history_frame(df, "日期", "最新价")
    return _filter_points_to_window(points, start_date=start_date, end_date=end_date)


def _fetch_global_index_hist_series(symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch one global-index history series from Eastmoney."""
    df = _call_with_resilience(ak.index_global_hist_em, symbol=symbol)
    if df is None or df.empty:
        return []
    points = _normalize_history_frame(df, "日期", "最新价")
    return _filter_points_to_window(points, start_date=start_date, end_date=end_date)


def _fetch_us_treasury_curve_series(column_name: str) -> list[tuple[str, float]]:
    """Fetch official U.S. Treasury yield-curve column history from the public table page."""
    current_month = dt.date.today().strftime("%Y%m")
    tables = _load_us_treasury_tables(current_month)
    for df in tables:
        cols = [str(col).strip() for col in df.columns]
        date_col = next((col for col in cols if col.lower() == "date"), None)
        if not date_col or column_name not in cols:
            continue
        return _normalize_history_frame(df, date_col, column_name)
    return []


def _load_us_treasury_tables(current_month: str) -> list[pd.DataFrame]:
    """Load and cache the current Treasury month table so 6M/10Y share one network fetch."""
    cache_ttl_seconds = 300
    cache_item = _TREASURY_CURVE_TABLE_CACHE.get(current_month)
    now = time.time()
    if cache_item and (now - cache_item[0]) <= cache_ttl_seconds:
        return cache_item[1]

    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"TextView?field_tdr_date_value_month={current_month}&type=daily_treasury_yield_curve"
    )
    try:
        tables = _call_with_resilience(lambda: pd.read_html(url))
    except Exception:
        tables = []
    if not tables:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            response = _call_with_resilience(lambda: requests.get(url, timeout=20, verify=False))
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
    _TREASURY_CURVE_TABLE_CACHE[current_month] = (now, tables)
    return tables


def _fetch_zhaomei_water_coal_series() -> list[tuple[str, float]]:
    """Fetch the public 水泥煤 price shown on 找煤网 mobile homepage."""

    def _load_html() -> str:
        response = requests.get("https://m.zhaomei.com/", timeout=10)
        response.raise_for_status()
        return response.text

    html = _call_with_resilience(_load_html)
    compact = re.sub(r"\s+", " ", html)
    section_match = re.search(
        r"水泥煤</span>现货参考价.*?<div class=\"floor_subtitle\">(\d{4}-\d{2}-\d{2})</div>.*?"
        r"水泥煤5500K\s*1\.0S</span></div>\s*<div class=\"bd\"><span>(\d+(?:\.\d+)?)</span>元/吨</div>",
        compact,
        flags=re.IGNORECASE,
    )
    if section_match:
        normalized_date = to_date_str(section_match.group(1))
        value = to_float(section_match.group(2))
        if normalized_date and value is not None:
            return [(normalized_date, value)]
    return []


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


def _fetch_single_external_series(spec: dict[str, str], start_date: str, end_date: str) -> tuple[list[tuple[str, float]], str]:
    """Fetch one external indicator series using the configured strategy."""
    fetch_kind = str(spec.get("fetch_kind") or "").strip()
    if fetch_kind == "global_future":
        symbol = str(spec.get("symbol") or "").strip()
        if not symbol:
            return [], ""
        points, chosen_symbol = _fetch_futures_global_hist_series([symbol], start_date, end_date)
        return points, f"futures_global_hist_em:{chosen_symbol or symbol}"
    if fetch_kind == "forex_hist":
        symbol = str(spec.get("symbol") or "").strip()
        if not symbol:
            return [], ""
        return _fetch_forex_hist_series(symbol, start_date, end_date), f"forex_hist_em:{symbol}"
    if fetch_kind == "global_index":
        symbol = str(spec.get("symbol") or "").strip()
        if not symbol:
            return [], ""
        return _fetch_global_index_hist_series(symbol, start_date, end_date), f"index_global_hist_em:{symbol}"
    if fetch_kind == "us_treasury_curve":
        column_name = str(spec.get("column") or "").strip()
        if not column_name:
            return [], ""
        points = _fetch_us_treasury_curve_series(column_name)
        return _filter_points_to_window(points, start_date=start_date, end_date=end_date), f"us_treasury_curve:{column_name}"
    if fetch_kind == "zhaomei_water_coal":
        return _fetch_zhaomei_water_coal_series(), "zhaomei_water_coal"
    if fetch_kind == "basis_proxy":
        basis_var = str(spec.get("basis_var") or "").strip()
        if not basis_var:
            return [], ""
        return _fetch_futures_basis_series(basis_var, start_date, end_date), f"futures_spot_price_daily:{basis_var}"
    return [], ""


def fetch_industry_price_rows(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    """Fetch industry cycle rows normalized for SQLite upsert."""
    rows, _ = fetch_industry_price_rows_with_diagnostics(start_date=start_date, end_date=end_date)
    return rows


def fetch_industry_price_rows_with_diagnostics(
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch industry rows and runtime diagnostics for source health and failures."""
    start_date = start_date or _days_ago_yyyymmdd(120)
    end_date = end_date or _today_yyyymmdd()
    out: list[dict[str, Any]] = []
    indicator_status: dict[str, dict[str, Any]] = {}
    dns_snapshot = _build_dns_snapshot()

    for spec in INDUSTRY_INDICATOR_SPECS:
        indicator_key = spec["indicator_key"]
        expected_hosts = _expected_hosts_for_spec(spec)
        indicator_status[indicator_key] = {
            "status": "unknown",
            "source": None,
            "error": None,
            "hosts": expected_hosts,
        }
        try:
            points, source = _fetch_single_industry_series(spec, start_date=start_date, end_date=end_date)
        except Exception as exc:
            # API assumption: upstream instability is common; continue with other indicators.
            logger.warning("industry_cycles indicator=%s fetch_failed err=%s", indicator_key, exc)
            indicator_status[indicator_key] = {
                "status": "fetch_failed",
                "source": None,
                "error": str(exc),
                "hosts": expected_hosts,
            }
            continue
        source_name = (source or "").split(":", 1)[0] if source else ""
        source_hosts = _resolve_source_hosts(source_name)
        status_text = "ok" if points else "no_data"
        dns_hosts = source_hosts or expected_hosts
        if dns_hosts and any(dns_snapshot.get(host) == "dns_failed" for host in dns_hosts):
            status_text = "dns_failed"
        indicator_status[indicator_key] = {
            "status": status_text,
            "source": source or None,
            "error": None,
            "hosts": source_hosts or expected_hosts,
        }
        logger.info(
            "industry_cycles indicator=%s points=%d source=%s",
            indicator_key,
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
    diagnostics = {
        "dns": dns_snapshot,
        "indicator_status": indicator_status,
    }
    # TODO: persist per-source refresh diagnostics for trend analysis.
    return out, diagnostics


def fetch_external_data_rows(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    """Fetch external indicator rows normalized for SQLite upsert."""
    rows, _ = fetch_external_data_rows_with_diagnostics(start_date=start_date, end_date=end_date)
    return rows


def fetch_external_data_rows_with_diagnostics(
    start_date: str | None = None,
    end_date: str | None = None,
    indicator_keys: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch external indicator rows and runtime diagnostics for source health and failures."""
    start_date = start_date or _days_ago_yyyymmdd(400)
    end_date = end_date or _today_yyyymmdd()
    out: list[dict[str, Any]] = []
    indicator_status: dict[str, dict[str, Any]] = {}
    dns_snapshot = _build_dns_snapshot()
    requested_keys = {str(item).strip() for item in (indicator_keys or set()) if str(item).strip()}

    for spec in EXTERNAL_DATA_SPECS:
        indicator_key = spec["indicator_key"]
        if requested_keys and indicator_key not in requested_keys:
            continue
        expected_hosts = _expected_hosts_for_external_spec(spec)
        indicator_status[indicator_key] = {
            "status": "unknown",
            "source": None,
            "error": None,
            "hosts": expected_hosts,
        }
        try:
            points, fetch_source = _fetch_single_external_series(spec, start_date=start_date, end_date=end_date)
        except Exception as exc:
            logger.warning("external_data indicator=%s fetch_failed err=%s", indicator_key, exc)
            indicator_status[indicator_key] = {
                "status": "fetch_failed",
                "source": None,
                "error": str(exc),
                "hosts": expected_hosts,
            }
            continue

        status_text = str(spec.get("status_on_success") or "ok")
        if not points:
            status_text = "no_data"
        if expected_hosts and any(dns_snapshot.get(host) == "dns_failed" for host in expected_hosts):
            status_text = "dns_failed"

        indicator_status[indicator_key] = {
            "status": status_text,
            "source": fetch_source or None,
            "error": None,
            "hosts": expected_hosts,
        }
        logger.info(
            "external_data indicator=%s points=%d source=%s",
            indicator_key,
            len(points),
            fetch_source or "none",
        )
        for date_text, value in points:
            out.append(
                {
                    "indicator_key": indicator_key,
                    "indicator": spec["indicator"],
                    "trade_date": date_text,
                    "value": value,
                    "source": spec["source"],
                    "source_url": spec["source_url"],
                    "note": spec["note"],
                }
            )

    diagnostics = {
        "dns": dns_snapshot,
        "indicator_status": indicator_status,
    }
    return out, diagnostics
