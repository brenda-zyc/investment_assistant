from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
from io import StringIO
import logging
import re
import socket
import time
import warnings
from typing import Any
from urllib.parse import urljoin

import akshare as ak
import pandas as pd
import requests
from bs4 import BeautifulSoup

from app.services.common import _call_with_resilience, _find_col, to_date_str, to_float

logger = logging.getLogger(__name__)

_HOST_RESOLVE_OK_CACHE: dict[str, float] = {}
_TREASURY_CURVE_TABLE_CACHE: dict[str, tuple[float, list[pd.DataFrame]]] = {}
INDUSTRY_FETCH_MAX_WORKERS = 4

# API assumption: these hosts are the critical availability gates for each upstream family.
_SOURCE_HOSTS: dict[str, list[str]] = {
    "futures_global_hist_em": ["push2his.eastmoney.com"],
    "futures_zh_daily_sina": ["stock2.finance.sina.com.cn"],
    "spot_hist_sge": ["www.sge.com.cn"],
    "macro_china_construction_price_index": ["datacenter-web.eastmoney.com"],
    "spot_hog_lean_price_soozhu": ["www.soozhu.com"],
    "spot_corn_price_soozhu": ["www.soozhu.com"],
    "moa_market_info": ["scs.moa.gov.cn", "www.moa.gov.cn"],
    "futures_spot_price_daily": ["www.100ppi.com"],
    "forex_hist_em": ["push2his.eastmoney.com"],
    "index_global_hist_em": ["push2his.eastmoney.com"],
    "us_treasury_curve": ["home.treasury.gov"],
    "zhaomei_water_coal": ["m.zhaomei.com"],
    "sxcoal_cci5500": ["www.sxcoal.com"],
    "cempi_index": ["index.ccement.com"],
}

INDUSTRY_INDICATOR_SPECS: list[dict[str, str]] = [
    {
        "industry": "Energy",
        "indicator_key": "brent_oil",
        "indicator": "brent_oil",
        "display_name": "布伦特原油价格",
        "global_symbols": "B00Y,CL00Y",
        "sina_contract": "SC0",
        "basis_var": "SC",
    },
    {
        "industry": "Energy",
        "indicator_key": "thermal_coal_index",
        "indicator": "thermal_coal_index",
        "display_name": "动力煤价格指数（CCI5500）",
        "special_source": "sxcoal_cci5500",
        "source_name": "Sxcoal",
        "source_url": "https://www.sxcoal.com/",
    },
    {
        "industry": "New Energy & Metals",
        "indicator_key": "lithium_carbonate",
        "indicator": "lithium_carbonate",
        "display_name": "碳酸锂价格",
        "sina_contract": "LC0",
        "basis_var": "LC",
    },
    {
        "industry": "New Energy & Metals",
        "indicator_key": "copper_price",
        "indicator": "copper_price",
        "display_name": "铜价",
        "sina_contract": "CU0",
        "basis_var": "CU",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "rebar_price",
        "indicator": "rebar_price",
        "display_name": "螺纹钢价格",
        "sina_contract": "RB0",
        "basis_var": "RB",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "iron_ore_price",
        "indicator": "iron_ore_price",
        "display_name": "铁矿石价格",
        "sina_contract": "I0",
        "basis_var": "I",
    },
    {
        "industry": "Steel & Construction",
        "indicator_key": "cement_price_index",
        "indicator": "cement_price_index",
        "display_name": "水泥价格指数（CEMPI）",
        "special_source": "cempi_index",
        "source_name": "水泥网",
        "source_url": "https://index.ccement.com/",
    },
    {
        "industry": "Solar",
        "indicator_key": "silicon_wafer_price",
        "indicator": "silicon_wafer_price",
        "display_name": "硅片价格",
        "sina_contract": "SI0",
        "basis_var": "SI",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "pork_wholesale_price_moa",
        "indicator": "pork_wholesale_price_moa",
        "display_name": "猪肉平均批发价（农业农村部）",
        "special_source": "moa_pork",
        "source_name": "农业农村部",
        "source_url": "https://www.moa.gov.cn/xw/zxfb/",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "live_hog_spot_price_soozhu",
        "indicator": "live_hog_spot_price_soozhu",
        "display_name": "生猪价格（搜猪网）",
        "special_source": "soozhu_pork",
        "source_name": "搜猪网",
        "source_url": "https://www.soozhu.com/",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "corn_price",
        "indicator": "corn_price",
        "display_name": "玉米价格",
        "special_source": "soozhu_corn",
        "sina_contract": "C0",
        "basis_var": "C",
    },
    {
        "industry": "Agriculture",
        "indicator_key": "beef_price",
        "indicator": "beef_price",
        "display_name": "牛肉价格",
        "special_source": "moa_beef",
    },
    {
        "industry": "Chemicals",
        "indicator_key": "methanol_price",
        "indicator": "methanol_price",
        "display_name": "甲醇价格",
        "sina_contract": "MA0",
        "basis_var": "MA",
    },
    {
        "industry": "Chemicals",
        "indicator_key": "rubber_price",
        "indicator": "rubber_price",
        "display_name": "橡胶价格",
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
        "fetch_kind": "sge_spot",
        "symbol": "Au(T+D)",
        "source": "上海黄金交易所",
        "source_url": "https://www.sge.com.cn/sjzx/mrhq",
        "note": "直接抓取上金所 Au(T+D) 历史行情最新值。",
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
        "fetch_kind": "thermal_coal_proxy",
        "sina_contract": "ZC0",
        "basis_var": "ZC",
        "source": "新浪财经",
        "source_url": "https://finance.sina.com.cn/futures/quotes/ZC0.shtml",
        "note": "优先抓取新浪动力煤主连日线，失败时回退到 100ppi 代理值。",
        "status_on_success": "ok",
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


def _all_hosts_dns_failed(hosts: list[str], dns_snapshot: dict[str, str]) -> bool:
    """Return True when every expected upstream host fails DNS preflight."""
    return bool(hosts) and all(dns_snapshot.get(host) == "dns_failed" for host in hosts)


def _expected_hosts_for_spec(spec: dict[str, str]) -> list[str]:
    """Infer candidate hosts for an indicator based on configured source fallbacks."""
    hosts: set[str] = set()
    if str(spec.get("global_symbols") or "").strip():
        hosts.update(_resolve_source_hosts("futures_global_hist_em"))
    special_source = str(spec.get("special_source") or "").strip()
    if special_source == "sxcoal_cci5500":
        hosts.update(_resolve_source_hosts("sxcoal_cci5500"))
    if special_source == "cempi_index":
        hosts.update(_resolve_source_hosts("cempi_index"))
    if special_source == "construction_index":
        hosts.update(_resolve_source_hosts("macro_china_construction_price_index"))
    if special_source == "soozhu_pork":
        hosts.update(_resolve_source_hosts("spot_hog_lean_price_soozhu"))
    if special_source == "soozhu_corn":
        hosts.update(_resolve_source_hosts("spot_corn_price_soozhu"))
    if special_source == "moa_pork":
        hosts.update(_resolve_source_hosts("moa_market_info"))
    if special_source == "moa_beef":
        hosts.update(_resolve_source_hosts("moa_market_info"))
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
    if fetch_kind == "sge_spot":
        return _resolve_source_hosts("spot_hist_sge")
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
    if fetch_kind == "thermal_coal_proxy":
        return sorted(
            {
                *(_resolve_source_hosts("futures_zh_daily_sina")),
                *(_resolve_source_hosts("futures_spot_price_daily")),
            }
        )
    return []


def _fetch_futures_basis_series(var_symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch one commodity spot series from futures basis endpoint by contract symbol."""
    if not _is_host_resolvable("www.100ppi.com"):
        logger.warning("industry_cycles host_unreachable=www.100ppi.com skip_symbol=%s", var_symbol)
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
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
    last_exc: Exception | None = None
    for symbol in symbol_candidates:
        try:
            df = _call_with_resilience(ak.futures_global_hist_em, symbol=symbol)
        except Exception as exc:
            logger.warning("industry_cycles global_hist failed symbol=%s err=%s", symbol, exc)
            last_exc = exc
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
    if last_exc is not None:
        raise last_exc
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


def _fetch_sge_spot_hist_series(symbol: str, start_date: str, end_date: str) -> list[tuple[str, float]]:
    """Fetch SGE daily close history for precious-metal spot/T+D instruments."""
    df = _call_with_resilience(ak.spot_hist_sge, symbol=symbol)
    if df is None or df.empty:
        return []
    points = _normalize_history_frame(df, "date", "close")
    return _filter_points_to_window(points, start_date=start_date, end_date=end_date)


def _fetch_construction_index_series() -> list[tuple[str, float]]:
    """Fetch construction-price index history."""
    df = _call_with_resilience(ak.macro_china_construction_price_index)
    if df is None or df.empty:
        return []
    return _normalize_history_frame(df, "日期", "最新值")


def _parse_sxcoal_cci5500_html(html: str) -> list[tuple[str, float]]:
    """Parse public Sxcoal CCI5500 snippets into normalized index points."""
    compact = re.sub(r"\s+", " ", html or "")
    points: list[tuple[str, float]] = []
    year = dt.date.today().year

    direct_patterns = [
        r"(20\d{2}-\d{2}-\d{2}).{0,120}?CCI5500.{0,80}?(?:上涨|下跌|报|为)?\s*([0-9]+(?:\.[0-9]+)?)\s*元/吨",
        r"CCI5500.{0,120}?(20\d{2}-\d{2}-\d{2}).{0,80}?([0-9]+(?:\.[0-9]+)?)\s*元/吨",
    ]
    for pattern in direct_patterns:
        for match in re.finditer(pattern, compact, flags=re.IGNORECASE):
            date_text = to_date_str(match.group(1))
            value = to_float(match.group(2))
            if date_text and value is not None:
                points.append((date_text, value))
        if points:
            return _dedupe_points(points)

    md_match = re.search(r"(\d{1,2})月(\d{1,2})日CCI5500", compact)
    value_match = re.search(r"CCI5500\s*([0-9]+(?:\.[0-9]+)?)\s*元/吨", compact, flags=re.IGNORECASE)
    if md_match and value_match:
        month = int(md_match.group(1))
        day = int(md_match.group(2))
        value = to_float(value_match.group(1))
        if value is not None:
            points.append((f"{year:04d}-{month:02d}-{day:02d}", value))
    return _dedupe_points(points)


def _fetch_sxcoal_cci5500_series(
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[tuple[str, float]]:
    """Fetch Sxcoal CCI5500 thermal-coal index from public search/article pages."""

    def _load_html() -> str:
        response = requests.get("https://www.sxcoal.com/news/search?wd=CCI5500", timeout=12)
        response.raise_for_status()
        response.encoding = getattr(response, "apparent_encoding", None) or getattr(response, "encoding", None) or "utf-8"
        return response.text

    html = _call_with_resilience(_load_html)
    points = _parse_sxcoal_cci5500_html(html)
    return _filter_points_to_window(points, start_date=start_date, end_date=end_date)


def _parse_cempi_index_html(html: str) -> list[tuple[str, float]]:
    """Parse public CEMPI index page snippets into normalized index points."""
    compact = re.sub(r"\s+", " ", html or "")
    patterns = [
        r"(20\d{2}-\d{2}-\d{2}).{0,120}?CEMPI.{0,120}?([0-9]+(?:\.[0-9]+)?)",
        r"CEMPI.{0,120}?(20\d{2}-\d{2}-\d{2}).{0,80}?([0-9]+(?:\.[0-9]+)?)",
    ]
    points: list[tuple[str, float]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, compact, flags=re.IGNORECASE):
            date_text = to_date_str(match.group(1))
            value = to_float(match.group(2))
            # CEMPI is a national index, not a rank counter; reject placeholder-like low integers.
            if value is not None and not (50.0 <= value <= 300.0):
                continue
            if date_text and value is not None:
                points.append((date_text, value))
        if points:
            break
    return _dedupe_points(points)


def _fetch_cempi_index_series(
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[tuple[str, float]]:
    """Fetch water-cement price index (CEMPI) from the public Ccement index page."""

    def _load_html() -> str:
        response = requests.get("https://index.ccement.com/", timeout=12)
        response.raise_for_status()
        response.encoding = getattr(response, "apparent_encoding", None) or getattr(response, "encoding", None) or "utf-8"
        return response.text

    html = _call_with_resilience(_load_html)
    points = _parse_cempi_index_html(html)
    return _filter_points_to_window(points, start_date=start_date, end_date=end_date)


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


def _extract_moa_article_date(article_url: str) -> str | None:
    """Extract article date from MOA article URL when the path embeds `tYYYYMMDD_`."""
    url_match = re.search(r"t(\d{4})(\d{2})(\d{2})_", article_url)
    if not url_match:
        return None
    return f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}"


def _build_moa_wholesale_price_patterns(product_label: str) -> list[str]:
    """Return regular expressions for MOA wholesale price articles for one product."""
    label = re.escape(product_label)
    return [
        rf"{label}(?:平均)?(?:批发)?价格为?每公斤\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        rf"{label}(?:平均)?(?:批发)?价格为?\s*([0-9]+(?:\.[0-9]+)?)\s*元/公斤",
        rf"{label}(?:平均)?(?:批发)?价格每公斤\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        rf"{label}(?:平均)?(?:批发)?价格\s*([0-9]+(?:\.[0-9]+)?)\s*元/公斤",
        rf"{label}(?:平均)?(?:批发)?(?:价格)?(?:为)?\s*([0-9]+(?:\.[0-9]+)?)\s*元/公斤",
        rf"{label}(?:平均)?(?:批发)?(?:价格)?(?:为)?每公斤\s*([0-9]+(?:\.[0-9]+)?)\s*元",
    ]


def _fetch_moa_wholesale_series(
    product_label: str,
    logger_key: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_pages: int = 8,
    max_articles: int = 40,
) -> list[tuple[str, float]]:
    """Fetch MOA wholesale price points from public market-info article pages."""
    listing_roots = [
        "https://scs.moa.gov.cn/scxxfb/",
        "https://www.moa.gov.cn/xw/zxfb/",
    ]
    article_candidates: list[tuple[int, str]] = []
    seen_urls: set[str] = set()
    price_patterns = _build_moa_wholesale_price_patterns(product_label)
    title_hints = (product_label, "市场动态", "市场信息", "农产品", "批发价格")

    def _load_html(url: str) -> str:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        response_encoding = getattr(response, "encoding", None)
        apparent_encoding = getattr(response, "apparent_encoding", None)
        if not response_encoding or str(response_encoding).lower() == "iso-8859-1":
            response.encoding = apparent_encoding or "utf-8"
        return response.text

    for root_url in listing_roots:
        for page_index in range(max_pages):
            listing_url = root_url if page_index == 0 else urljoin(root_url, f"index_{page_index}.htm")
            try:
                listing_html = _call_with_resilience(lambda url=listing_url: _load_html(url))
            except Exception as exc:
                logger.warning("industry_cycles %s listing_failed url=%s err=%s", logger_key, listing_url, exc)
                continue
            if not listing_html:
                continue
            soup = BeautifulSoup(listing_html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                article_url = urljoin(listing_url, href)
                if not href or not article_url.endswith(".htm") or article_url in seen_urls:
                    continue
                title_text = (anchor.get("title") or anchor.get_text(" ", strip=True) or "").strip()
                if title_text and not any(hint in title_text for hint in title_hints):
                    continue
                seen_urls.add(article_url)
                priority = 0 if "牛肉" in title_text else 1
                article_candidates.append((priority, article_url))

    points: list[tuple[str, float]] = []
    article_candidates.sort(key=lambda item: item[1], reverse=True)
    article_candidates.sort(key=lambda item: item[0])
    start_text = to_date_str(start_date)
    end_text = to_date_str(end_date)
    for _, article_url in article_candidates[:max_articles]:
        article_date_hint = _extract_moa_article_date(article_url)
        if end_text and article_date_hint and article_date_hint > end_text:
            continue
        if start_text and article_date_hint and article_date_hint < start_text:
            if points:
                break
            continue
        try:
            article_html = _call_with_resilience(lambda url=article_url: _load_html(url))
        except Exception as exc:
            logger.warning("industry_cycles %s article_failed url=%s err=%s", logger_key, article_url, exc)
            continue
        if not article_html:
            continue
        soup = BeautifulSoup(article_html, "html.parser")
        article_text = soup.get_text(" ", strip=True)

        trade_date = None
        date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", article_text)
        if date_match:
            trade_date = (
                f"{int(date_match.group(1)):04d}-"
                f"{int(date_match.group(2)):02d}-"
                f"{int(date_match.group(3)):02d}"
            )
        else:
            trade_date = article_date_hint

        if not trade_date:
            continue
        if end_text and trade_date > end_text:
            continue
        if start_text and trade_date < start_text:
            if points:
                break
            continue

        value = None
        for pattern in price_patterns:
            price_match = re.search(pattern, article_text)
            if price_match:
                value = to_float(price_match.group(1))
                break
        if value is None:
            continue
        points.append((trade_date, value))

    return _dedupe_points(points)


def _fetch_moa_beef_series(
    start_date: str | None = None,
    end_date: str | None = None,
    max_pages: int = 8,
    max_articles: int = 40,
) -> list[tuple[str, float]]:
    """Fetch beef wholesale price points from MOA market-info article pages."""
    return _fetch_moa_wholesale_series(
        "牛肉",
        "moa_beef",
        start_date=start_date,
        end_date=end_date,
        max_pages=max_pages,
        max_articles=max_articles,
    )


def _fetch_moa_pork_series(
    start_date: str | None = None,
    end_date: str | None = None,
    max_pages: int = 8,
    max_articles: int = 40,
) -> list[tuple[str, float]]:
    """Fetch pork wholesale price points from MOA market-info article pages."""
    return _fetch_moa_wholesale_series(
        "猪肉",
        "moa_pork",
        start_date=start_date,
        end_date=end_date,
        max_pages=max_pages,
        max_articles=max_articles,
    )


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
            response = _call_with_resilience(lambda: requests.get(url, timeout=20))
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


def _max_recent_start_date(start_date: str, end_date: str, max_lookback_days: int) -> str:
    """Return a start date capped to a recent lookback window while preserving valid input order."""
    start_text = to_date_str(start_date)
    end_text = to_date_str(end_date)
    if not start_text or not end_text:
        return start_date
    capped_start = (dt.date.fromisoformat(end_text) - dt.timedelta(days=max_lookback_days)).isoformat()
    return max(start_text, capped_start).replace("-", "")


def _fetch_single_industry_series(spec: dict[str, str], start_date: str, end_date: str) -> tuple[list[tuple[str, float]], str]:
    """Fetch one indicator series using priority-ordered source fallbacks."""
    indicator_key = spec["indicator_key"]

    global_symbols_text = str(spec.get("global_symbols") or "").strip()
    if global_symbols_text:
        candidates = [item.strip() for item in global_symbols_text.split(",") if item.strip()]
        try:
            points, chosen_symbol = _fetch_futures_global_hist_series(candidates, start_date, end_date)
            if points:
                return points, f"futures_global_hist_em:{chosen_symbol}"
        except Exception as exc:
            logger.warning("industry_cycles global source failed indicator=%s err=%s", indicator_key, exc)

    special_source = str(spec.get("special_source") or "").strip()
    if special_source == "sxcoal_cci5500":
        points = _fetch_sxcoal_cci5500_series(start_date=start_date, end_date=end_date)
        if points:
            return points, "sxcoal_cci5500"
    if special_source == "cempi_index":
        points = _fetch_cempi_index_series(start_date=start_date, end_date=end_date)
        if points:
            return points, "cempi_index"
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
    if special_source == "moa_pork":
        points = _fetch_moa_pork_series(
            start_date=start_date,
            end_date=end_date,
            max_pages=1,
            max_articles=12,
        )
        if points:
            return points, "moa_market_info"
    if special_source == "moa_beef":
        points = _fetch_moa_beef_series(
            start_date=start_date,
            end_date=end_date,
            max_pages=1,
            max_articles=12,
        )
        if points:
            return points, "moa_market_info"

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


def _classify_industry_fetch_exception(spec: dict[str, str], exc: Exception) -> str:
    """Classify known source-specific fetch failures into stable status labels."""
    special_source = str(spec.get("special_source") or "").strip()
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if special_source == "sxcoal_cci5500" and status_code == 403:
        return "blocked"
    if special_source == "sxcoal_cci5500" and "403" in str(exc):
        return "blocked"
    return "fetch_failed"


def _fetch_single_external_series(spec: dict[str, str], start_date: str, end_date: str) -> tuple[list[tuple[str, float]], str]:
    """Fetch one external indicator series using the configured strategy."""
    fetch_kind = str(spec.get("fetch_kind") or "").strip()
    if fetch_kind == "global_future":
        symbol = str(spec.get("symbol") or "").strip()
        if not symbol:
            return [], ""
        points, chosen_symbol = _fetch_futures_global_hist_series([symbol], start_date, end_date)
        return points, f"futures_global_hist_em:{chosen_symbol or symbol}"
    if fetch_kind == "sge_spot":
        symbol = str(spec.get("symbol") or "").strip()
        if not symbol:
            return [], ""
        return _fetch_sge_spot_hist_series(symbol, start_date, end_date), f"spot_hist_sge:{symbol}"
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
    if fetch_kind == "thermal_coal_proxy":
        sina_contract = str(spec.get("sina_contract") or "").strip()
        basis_var = str(spec.get("basis_var") or "").strip()
        if sina_contract:
            points = _fetch_futures_daily_sina_series(sina_contract, start_date, end_date)
            if points:
                return points, f"futures_zh_daily_sina:{sina_contract}"
        if basis_var:
            recent_start = _max_recent_start_date(start_date, end_date, max_lookback_days=14)
            return _fetch_futures_basis_series(basis_var, recent_start, end_date), f"futures_spot_price_daily:{basis_var}"
    return [], ""


def _external_row_metadata(spec: dict[str, str], fetch_source: str) -> tuple[str, str, str]:
    """Return display metadata matching the actual upstream source used for the cached point."""
    raw_source = (fetch_source or "").split(":", 1)[0]
    if raw_source == "spot_hist_sge":
        return (
            "上海黄金交易所",
            "https://www.sge.com.cn/sjzx/mrhq",
            "直接抓取上金所 Au(T+D) 历史行情最新值。",
        )
    if raw_source == "futures_zh_daily_sina":
        contract_symbol = fetch_source.split(":", 1)[1] if ":" in fetch_source else str(spec.get("sina_contract") or "")
        return (
            "新浪财经",
            f"https://finance.sina.com.cn/futures/quotes/{contract_symbol}.shtml",
            str(spec.get("note") or "").strip() or "直接抓取新浪财经期货主连历史行情最新值。",
        )
    if raw_source == "futures_spot_price_daily":
        return (
            "100ppi（代理）",
            "https://www.100ppi.com/sf/",
            "新浪动力煤主连未返回数据，回退到 100ppi 动力煤现货代理值。",
        )
    return (
        str(spec.get("source") or "-"),
        str(spec.get("source_url") or ""),
        str(spec.get("note") or "-"),
    )


def _external_success_status(spec: dict[str, str], fetch_source: str, points: list[tuple[str, float]]) -> str:
    """Return the success status that matches the actual source used for the fetched row."""
    if not points:
        return "no_data"
    raw_source = (fetch_source or "").split(":", 1)[0]
    if raw_source == "futures_spot_price_daily":
        return "proxy"
    return str(spec.get("status_on_success") or "ok")


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
    fetchable_specs: list[dict[str, str]] = []

    for spec in INDUSTRY_INDICATOR_SPECS:
        indicator_key = spec["indicator_key"]
        expected_hosts = _expected_hosts_for_spec(spec)
        indicator_status[indicator_key] = {
            "status": "unknown",
            "source": None,
            "error": None,
            "hosts": expected_hosts,
        }
        if _all_hosts_dns_failed(expected_hosts, dns_snapshot):
            indicator_status[indicator_key] = {
                "status": "dns_failed",
                "source": None,
                "error": None,
                "hosts": expected_hosts,
            }
            logger.warning(
                "industry_cycles indicator=%s dns_preflight_failed hosts=%s",
                indicator_key,
                ",".join(expected_hosts),
            )
            continue
        fetchable_specs.append(spec)

    fetch_results: dict[str, dict[str, Any]] = {}
    if fetchable_specs:
        max_workers = min(len(fetchable_specs), INDUSTRY_FETCH_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _fetch_single_industry_series,
                    spec,
                    start_date=start_date,
                    end_date=end_date,
                ): spec
                for spec in fetchable_specs
            }
            for future in as_completed(future_map):
                spec = future_map[future]
                indicator_key = spec["indicator_key"]
                expected_hosts = _expected_hosts_for_spec(spec)
                try:
                    points, source = future.result()
                except Exception as exc:
                    # API assumption: upstream instability is common; continue with other indicators.
                    logger.warning("industry_cycles indicator=%s fetch_failed err=%s", indicator_key, exc)
                    status_text = _classify_industry_fetch_exception(spec, exc)
                    fetch_results[indicator_key] = {
                        "points": [],
                        "source": None,
                        "status": status_text,
                        "error": str(exc),
                        "hosts": expected_hosts,
                    }
                    continue
                source_name = (source or "").split(":", 1)[0] if source else ""
                source_hosts = _resolve_source_hosts(source_name)
                fetch_results[indicator_key] = {
                    "points": points,
                    "source": source or None,
                    "status": "ok" if points else "no_data",
                    "error": None,
                    "hosts": source_hosts or expected_hosts,
                }

    for spec in INDUSTRY_INDICATOR_SPECS:
        indicator_key = spec["indicator_key"]
        result = fetch_results.get(indicator_key)
        if result is None:
            continue
        indicator_status[indicator_key] = {
            "status": result["status"],
            "source": result["source"],
            "error": result["error"],
            "hosts": result["hosts"],
        }
        logger.info(
            "industry_cycles indicator=%s points=%d source=%s",
            indicator_key,
            len(result["points"]),
            result["source"] or "none",
        )
        for date_text, value in result["points"]:
            out.append(
                {
                    "industry": spec["industry"],
                    "indicator": spec["indicator_key"],
                    "trade_date": date_text,
                    "value": value,
                    "source": result["source"],
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
        if _all_hosts_dns_failed(expected_hosts, dns_snapshot):
            indicator_status[indicator_key] = {
                "status": "dns_failed",
                "source": None,
                "error": None,
                "hosts": expected_hosts,
            }
            logger.warning(
                "external_data indicator=%s dns_preflight_failed hosts=%s",
                indicator_key,
                ",".join(expected_hosts),
            )
            continue
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

        status_text = _external_success_status(spec, fetch_source, points)

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
        display_source, display_source_url, display_note = _external_row_metadata(spec, fetch_source)
        for date_text, value in points:
            out.append(
                {
                    "indicator_key": indicator_key,
                    "indicator": spec["indicator"],
                    "trade_date": date_text,
                    "value": value,
                    "source": display_source,
                    "source_url": display_source_url,
                    "note": display_note,
                }
            )

    diagnostics = {
        "dns": dns_snapshot,
        "indicator_status": indicator_status,
    }
    return out, diagnostics
