from __future__ import annotations

from functools import lru_cache
import logging
import math
import re
from typing import Any

import akshare as ak
import pandas as pd

from app.services.common import _call_with_resilience, _find_col, to_date_str, to_float

logger = logging.getLogger(__name__)

_STOCK_NAME_RUNTIME_CACHE: dict[str, str] = {}


def normalize_stock_code(stock_code: str) -> str:
    """Validate and normalize a 6-digit A-share stock code."""
    code = stock_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("Stock code must be a 6-digit A-share code, e.g. 600519")
    return code


def fetch_price_data(stock_code: str) -> list[dict[str, Any]]:
    """Fetch and normalize A-share daily OHLCV price history."""
    df = _call_with_resilience(ak.stock_zh_a_hist, symbol=stock_code, period="daily", adjust="")

    if df is None or df.empty:
        return []

    column_map = {
        "日期": "trade_date",
        "date": "trade_date",
        "开盘": "open",
        "open": "open",
        "收盘": "close",
        "close": "close",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
    }
    normalized_columns: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip()
        if key in column_map:
            normalized_columns[col] = column_map[key]

    result: list[dict[str, Any]] = []
    for _, row in df.rename(columns=normalized_columns).iterrows():
        trade_date = to_date_str(row.get("trade_date"))
        if not trade_date:
            continue
        result.append(
            {
                "trade_date": trade_date,
                "open": to_float(row.get("open")),
                "close": to_float(row.get("close")),
                "high": to_float(row.get("high")),
                "low": to_float(row.get("low")),
                "volume": to_float(row.get("volume")),
                "amount": to_float(row.get("amount")),
            }
        )
    result.sort(key=lambda x: x["trade_date"])
    return result


def _extract_financial_rows_report_style(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Handle row-per-report format, e.g. columns include 报告期/日期 + 指标列."""
    cols = [str(c) for c in df.columns]
    date_col = _find_col(cols, ["报告期", "报告日期", "日期", "截止日期"])
    if not date_col:
        return []

    revenue_col = _find_col(cols, ["营业总收入", "营业收入", "主营业务收入"], ["增长"])
    net_profit_col = _find_col(cols, ["净利润", "归母净利润"], ["增长", "率"])
    roe_col = _find_col(cols, ["净资产收益率", "ROE"])
    debt_ratio_col = _find_col(cols, ["资产负债率", "负债率"])

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        date_text = to_date_str(row.get(date_col))
        if not date_text:
            continue
        report_year = int(date_text[:4])
        rows.append(
            {
                "report_year": report_year,
                "report_date": date_text,
                "revenue": to_float(row.get(revenue_col)) if revenue_col else None,
                "net_profit": to_float(row.get(net_profit_col)) if net_profit_col else None,
                "roe": to_float(row.get(roe_col)) if roe_col else None,
                "debt_ratio": to_float(row.get(debt_ratio_col)) if debt_ratio_col else None,
            }
        )
    return rows


_FINANCIAL_ROW_METRIC_SPEC: dict[str, dict[str, list[str]]] = {
    "revenue": {
        "include": ["营业总收入", "营业收入", "主营业务收入"],
        "exclude": ["增长", "同比", "每股", "占比"],
        "prefer": ["营业总收入", "营业收入"],
    },
    "net_profit": {
        "include": ["归母净利润", "净利润"],
        "exclude": ["增长", "同比", "每股", "扣非", "现金流"],
        "prefer": ["归母净利润", "净利润"],
    },
    "roe": {
        "include": ["净资产收益率", "ROE"],
        "exclude": ["增长", "同比"],
        "prefer": ["净资产收益率", "ROE"],
    },
    "debt_ratio": {
        "include": ["资产负债率", "负债率"],
        "exclude": ["增长", "同比"],
        "prefer": ["资产负债率", "负债率"],
    },
}


def _score_metric_name(
    metric_name: str,
    include: list[str],
    exclude: list[str],
    prefer: list[str],
) -> int | None:
    """Return preference score for a metric label, or None when label does not match."""
    if not metric_name:
        return None
    if not any(label in metric_name for label in include):
        return None
    if any(label in metric_name for label in exclude):
        return None

    score = 10
    for idx, preferred_label in enumerate(prefer):
        if preferred_label in metric_name:
            score = 100 - idx
            break
    return score


def _pick_best_metric_names(df: pd.DataFrame, metric_col: str) -> dict[str, str]:
    """Pick one best metric label per target metric key."""
    picked_metrics: dict[str, tuple[int, str]] = {}
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        for key, rule in _FINANCIAL_ROW_METRIC_SPEC.items():
            score = _score_metric_name(
                metric_name,
                include=rule["include"],
                exclude=rule["exclude"],
                prefer=rule["prefer"],
            )
            if score is None:
                continue
            current = picked_metrics.get(key)
            if current is None or score > current[0]:
                picked_metrics[key] = (score, metric_name)
    return {key: name for key, (_, name) in picked_metrics.items()}


def _extract_financial_rows_metric_style(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Handle metric-row format where first column is metric name and rest are report dates."""
    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    metric_col = "指标" if "指标" in cols else cols[0]
    date_cols = [col for col in cols if col != metric_col and to_date_str(col)]
    if not date_cols:
        return []
    best_metric_names = _pick_best_metric_names(df, metric_col)
    metric_name_to_key = {name: key for key, name in best_metric_names.items()}

    values_by_date: dict[str, dict[str, float | None]] = {}
    for col in date_cols:
        date_text = to_date_str(col)
        if date_text:
            values_by_date[date_text] = {}

    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        matched_key = metric_name_to_key.get(metric_name)
        if not matched_key:
            continue

        for col in date_cols:
            date_text = to_date_str(col)
            if not date_text:
                continue
            values_by_date[date_text][matched_key] = to_float(row.get(col))

    rows: list[dict[str, Any]] = []
    for report_date, metrics in values_by_date.items():
        rows.append(
            {
                "report_year": int(report_date[:4]),
                "report_date": report_date,
                "revenue": metrics.get("revenue"),
                "net_profit": metrics.get("net_profit"),
                "roe": metrics.get("roe"),
                "debt_ratio": metrics.get("debt_ratio"),
            }
        )
    return rows


def _deduplicate_by_year(rows: list[dict[str, Any]], years: int = 5) -> list[dict[str, Any]]:
    """Keep the latest record per year, capped by the requested year count."""
    if not rows:
        return []

    by_year: dict[int, dict[str, Any]] = {}
    sorted_rows = sorted(rows, key=lambda r: r.get("report_date", ""), reverse=True)
    for row in sorted_rows:
        year = int(row["report_year"])
        if year not in by_year:
            by_year[year] = row
        if len(by_year) >= years:
            break

    result = [by_year[y] for y in sorted(by_year.keys(), reverse=True)[:years]]
    return result[:years]


def fetch_financial_summary(stock_code: str) -> list[dict[str, Any]]:
    """Fetch and normalize recent annual financial metrics."""
    all_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for fetcher in (
        lambda: ak.stock_financial_abstract(symbol=stock_code),
        lambda: ak.stock_financial_analysis_indicator(symbol=stock_code),
    ):
        try:
            df = _call_with_resilience(fetcher)
            if df is None or df.empty:
                continue

            rows = _extract_financial_rows_report_style(df)
            if not rows:
                rows = _extract_financial_rows_metric_style(df)
            all_rows.extend(rows)
        except Exception as exc:  # pragma: no cover - network/API variations
            errors.append(str(exc))
            continue

    cleaned = _deduplicate_by_year(all_rows, years=5)
    if not cleaned and errors:
        raise RuntimeError("Unable to fetch financial data from upstream API")
    return cleaned


def _find_date_col(df: pd.DataFrame) -> str | None:
    """Locate the most likely date column in an upstream dataframe."""
    cols = [str(c) for c in df.columns]
    return _find_col(cols, ["日期", "date", "报告期", "报告日期", "截止日期", "trade_date"])


def _extract_series_from_row_style(
    df: pd.DataFrame,
    include_keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Extract metric series from row-wise financial tables."""
    exclude_keywords = exclude_keywords or []
    cols = [str(c) for c in df.columns]
    date_col = _find_date_col(df)
    if not date_col:
        return []

    value_col = _find_col(cols, include_keywords, exclude_keywords)
    if not value_col:
        return []

    points: list[tuple[str, float]] = []
    for _, row in df.iterrows():
        date_text = to_date_str(row.get(date_col))
        value = to_float(row.get(value_col))
        if not date_text or value is None:
            continue
        points.append((date_text, value))
    return points


def _extract_series_from_metric_style(
    df: pd.DataFrame,
    include_keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Extract metric series from metric-row / date-column shaped tables."""
    exclude_keywords = exclude_keywords or []
    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    metric_col = "指标" if "指标" in cols else cols[0]
    date_cols = [col for col in cols if col != metric_col and to_date_str(col)]
    if not date_cols:
        return []

    chosen_metric_name: str | None = None
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if not metric_name:
            continue
        if not any(keyword in metric_name for keyword in include_keywords):
            continue
        if any(keyword in metric_name for keyword in exclude_keywords):
            continue
        chosen_metric_name = metric_name
        break

    if not chosen_metric_name:
        return []

    points: list[tuple[str, float]] = []
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if metric_name != chosen_metric_name:
            continue
        for col in date_cols:
            date_text = to_date_str(col)
            value = to_float(row.get(col))
            if not date_text or value is None:
                continue
            points.append((date_text, value))
        break
    return points


def _dedupe_points(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Deduplicate points by date and return ascending date order."""
    bucket: dict[str, float] = {}
    for date_text, value in points:
        bucket[date_text] = value
    return sorted(bucket.items(), key=lambda x: x[0])


def fetch_valuation_series(stock_code: str) -> dict[str, list[tuple[str, float]]]:
    """Fetch PE/PB historical series for percentile calculations."""
    logger.info("stock_metrics endpoint=stock_a_indicator_lg symbol=%s", stock_code)
    df = _call_with_resilience(ak.stock_a_indicator_lg, symbol=stock_code)
    if df is None or df.empty:
        return {"pe_ttm": [], "pb": []}

    cols = [str(c) for c in df.columns]
    date_col = _find_date_col(df)
    pe_col = _find_col(cols, ["市盈率", "pe", "PE", "ttm"], ["分位", "百分位"])
    pb_col = _find_col(cols, ["市净率", "pb", "PB"], ["分位", "百分位"])

    pe_points: list[tuple[str, float]] = []
    pb_points: list[tuple[str, float]] = []
    if date_col:
        for _, row in df.iterrows():
            date_text = to_date_str(row.get(date_col))
            if not date_text:
                continue
            if pe_col:
                pe_value = to_float(row.get(pe_col))
                if pe_value is not None:
                    pe_points.append((date_text, pe_value))
            if pb_col:
                pb_value = to_float(row.get(pb_col))
                if pb_value is not None:
                    pb_points.append((date_text, pb_value))

    pe_points = _dedupe_points(pe_points)
    pb_points = _dedupe_points(pb_points)
    logger.info("stock_metrics points symbol=%s pe_ttm=%d pb=%d", stock_code, len(pe_points), len(pb_points))
    return {"pe_ttm": pe_points, "pb": pb_points}


@lru_cache(maxsize=1)
def _get_stock_name_map() -> dict[str, str]:
    """Load and cache A-share stock code-name map."""
    logger.info("stock_name endpoint=stock_info_a_code_name")
    df = _call_with_resilience(ak.stock_info_a_code_name)
    if df is None or df.empty:
        return {}

    cols = [str(c) for c in df.columns]
    code_col = _find_col(cols, ["code", "代码", "证券代码"])
    name_col = _find_col(cols, ["name", "名称", "简称"])
    if not code_col or not name_col:
        return {}

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get(code_col, "")).strip()
        if not raw_code:
            continue
        normalized_code = raw_code.zfill(6)
        if not re.fullmatch(r"\d{6}", normalized_code):
            continue
        name = str(row.get(name_col, "")).strip()
        if name:
            mapping[normalized_code] = name
    logger.info("stock_name loaded=%d", len(mapping))
    return mapping


def fetch_stock_names(stock_codes: list[str]) -> dict[str, str]:
    """Fetch stock names for requested symbols using cached code-name mapping."""
    normalized_codes = [normalize_stock_code(code) for code in stock_codes]
    if not normalized_codes:
        return {}
    name_map = _get_stock_name_map()
    out: dict[str, str] = {}
    unresolved: list[str] = []
    for code in normalized_codes:
        resolved = name_map.get(code) or _STOCK_NAME_RUNTIME_CACHE.get(code, "")
        out[code] = resolved
        if resolved:
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved
        else:
            unresolved.append(code)

    for code in unresolved:
        resolved = _fetch_stock_name_single(code)
        if resolved:
            out[code] = resolved
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved
    return out


def _fetch_stock_name_single(stock_code: str) -> str:
    """Fetch one stock name from a single-symbol profile endpoint."""
    try:
        logger.info("stock_name endpoint=stock_individual_info_em symbol=%s", stock_code)
        df = _call_with_resilience(lambda: ak.stock_individual_info_em(symbol=stock_code))
    except Exception:
        return ""
    if df is None or df.empty:
        return ""

    cols = [str(c) for c in df.columns]
    key_col = _find_col(cols, ["item", "项目", "指标"])
    value_col = _find_col(cols, ["value", "数值", "内容"])
    if not key_col or not value_col:
        return ""

    for _, row in df.iterrows():
        key_text = str(row.get(key_col, "")).strip()
        if "简称" not in key_text and "名称" not in key_text:
            continue
        value_text = str(row.get(value_col, "")).strip()
        if value_text:
            return value_text
    return ""


def fetch_realtime_quotes(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch realtime quote snapshot for specified A-share symbols."""
    normalized_codes = [normalize_stock_code(code) for code in stock_codes]
    if not normalized_codes:
        return {}

    logger.info("realtime endpoint=stock_zh_a_spot_em symbols=%d", len(normalized_codes))
    df = _call_with_resilience(ak.stock_zh_a_spot_em)
    if df is None or df.empty:
        return {}

    cols = [str(c) for c in df.columns]
    code_col = _find_col(cols, ["代码", "symbol", "证券代码"])
    name_col = _find_col(cols, ["名称", "简称", "name"])
    price_col = _find_col(cols, ["最新价", "现价", "price"])
    change_pct_col = _find_col(cols, ["涨跌幅", "change", "pct"], ["成交", "换手"])
    update_col = _find_col(cols, ["更新时间", "时间", "update"])
    if not code_col:
        return {}

    name_fallback_map = fetch_stock_names(normalized_codes)
    target_set = set(normalized_codes)
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get(code_col, "")).strip()
        code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
        if code not in target_set:
            continue
        row_name = str(row.get(name_col, "")).strip() if name_col else ""
        resolved_name = row_name or name_fallback_map.get(code, "")
        if resolved_name:
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved_name
        out[code] = {
            "symbol": code,
            "name": resolved_name or None,
            "latest_price": to_float(row.get(price_col)) if price_col else None,
            "change_pct": to_float(row.get(change_pct_col)) if change_pct_col else None,
            "updated_at": str(row.get(update_col)).strip() if update_col else None,
        }
    logger.info("realtime points returned=%d", len(out))
    return out


def fetch_financial_metric_series(stock_code: str) -> dict[str, list[tuple[str, float]]]:
    """Fetch ROE/ROIC/Revenue series from financial endpoints."""
    endpoint_fetchers = (
        ("stock_financial_analysis_indicator", lambda: ak.stock_financial_analysis_indicator(symbol=stock_code)),
        ("stock_financial_abstract", lambda: ak.stock_financial_abstract(symbol=stock_code)),
    )

    metric_specs = {
        "roe": (["净资产收益率", "ROE"], ["增长", "同比"]),
        "roic": (["投入资本回报率", "ROIC", "资本回报率"], ["增长", "同比"]),
        "revenue": (["营业总收入", "营业收入", "主营业务收入"], ["增长", "同比", "占比"]),
    }
    out: dict[str, list[tuple[str, float]]] = {key: [] for key in metric_specs}

    for endpoint_name, fetcher in endpoint_fetchers:
        try:
            logger.info("stock_metrics endpoint=%s symbol=%s", endpoint_name, stock_code)
            df = _call_with_resilience(fetcher)
        except Exception as exc:
            logger.warning("stock_metrics endpoint=%s symbol=%s failed=%s", endpoint_name, stock_code, exc)
            continue

        if df is None or df.empty:
            continue

        for metric_name, (include_keywords, exclude_keywords) in metric_specs.items():
            row_points = _extract_series_from_row_style(df, include_keywords, exclude_keywords)
            metric_points = _extract_series_from_metric_style(df, include_keywords, exclude_keywords)
            merged = _dedupe_points(out[metric_name] + row_points + metric_points)
            out[metric_name] = merged

    logger.info(
        "stock_metrics points symbol=%s roe=%d roic=%d revenue=%d",
        stock_code,
        len(out["roe"]),
        len(out["roic"]),
        len(out["revenue"]),
    )
    return out


def build_revenue_cagr_5y_series(revenue_points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Build rolling 5-year revenue CAGR series from raw revenue observations."""
    if not revenue_points:
        return []

    points = [(pd.to_datetime(d), v) for d, v in revenue_points if v is not None and v > 0]
    points.sort(key=lambda x: x[0])
    out: list[tuple[str, float]] = []

    for idx, (date_now, rev_now) in enumerate(points):
        best_prev_value: float | None = None
        for prev_date, prev_value in points[:idx]:
            year_diff = (date_now - prev_date).days / 365.25
            if year_diff >= 5 and prev_value > 0:
                best_prev_value = prev_value
        if best_prev_value is None:
            continue
        try:
            cagr = math.pow(rev_now / best_prev_value, 1 / 5) - 1
        except (ValueError, ZeroDivisionError):
            continue
        out.append((date_now.date().isoformat(), cagr))

    return _dedupe_points(out)
