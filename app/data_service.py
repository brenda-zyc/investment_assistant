from __future__ import annotations

import datetime as dt
import logging
import math
import os
import re
import time
from contextlib import contextmanager
from typing import Any

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


def normalize_stock_code(stock_code: str) -> str:
    """Validate and normalize a 6-digit A-share stock code."""
    code = stock_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("Stock code must be a 6-digit A-share code, e.g. 600519")
    return code


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


@contextmanager
def without_proxy_env():
    """Temporarily clear proxy env vars for flaky proxy environments."""
    backup: dict[str, str | None] = {k: os.environ.get(k) for k in PROXY_ENV_KEYS + ["NO_PROXY", "no_proxy"]}
    try:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _should_retry_without_proxy(exc: Exception) -> bool:
    """Return True when error message indicates proxy-related failure."""
    msg = str(exc).lower()
    return "proxyerror" in msg or "unable to connect to proxy" in msg


def _should_retry_network(exc: Exception) -> bool:
    """Return True when error message suggests transient network instability."""
    msg = str(exc).lower()
    retry_patterns = (
        "connection aborted",
        "remotedisconnected",
        "remote end closed connection without response",
        "max retries exceeded",
        "read timed out",
        "connect timeout",
        "temporarily unavailable",
        "chunkedencodingerror",
    )
    return any(pattern in msg for pattern in retry_patterns)


def _call_with_resilience(func, *args, **kwargs):
    """Call upstream function with retry and proxy-bypass fallback."""
    # API assumption: upstream providers occasionally fail with transient network errors.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - upstream/network variability
            last_exc = exc
            if _should_retry_without_proxy(exc):
                try:
                    with without_proxy_env():
                        return func(*args, **kwargs)
                except Exception as proxy_exc:
                    last_exc = proxy_exc
            if not _should_retry_network(last_exc):
                raise last_exc
            time.sleep(0.8 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def to_float(value: Any) -> float | None:
    """Convert mixed numeric text into float, returning None for invalid values."""
    # Data cleaning rule: treat '--', empty text, and NaN-like values as missing.
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)

    text = str(value).strip()
    if not text or text in {"--", "nan", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_date_str(value: Any) -> str | None:
    """Convert many date-like formats into ISO date string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y/%m"):
        try:
            parsed = dt.datetime.strptime(text[: len(fmt)], fmt)
            if fmt in {"%Y-%m", "%Y/%m"}:
                parsed = parsed.replace(day=1)
            return parsed.date().isoformat()
        except ValueError:
            continue

    try:
        parsed = pd.to_datetime(text)
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
    except Exception:
        return None


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


def _find_col(columns: list[str], candidates: list[str], exclude: list[str] | None = None) -> str | None:
    """Find the first column containing candidate keywords while avoiding exclusions."""
    exclude = exclude or []
    for col in columns:
        col_clean = col.replace(" ", "")
        if any(ex in col_clean for ex in exclude):
            continue
        if any(keyword in col_clean for keyword in candidates):
            return col
    return None


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


def _extract_financial_rows_metric_style(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Handle metric-row format where first column is metric name and the rest are report dates.
    Example:
        指标 | 2024-12-31 | 2023-12-31 | ...
    """
    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    metric_col = "指标" if "指标" in cols else cols[0]
    date_cols = [col for col in cols if col != metric_col and to_date_str(col)]
    if not date_cols:
        return []

    metric_spec = {
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

    picked_metrics: dict[str, tuple[int, str]] = {}
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if not metric_name:
            continue
        for key, rule in metric_spec.items():
            include = rule["include"]
            exclude = rule["exclude"]
            prefer = rule["prefer"]
            if not any(label in metric_name for label in include):
                continue
            if any(label in metric_name for label in exclude):
                continue

            score = 10
            for idx, preferred_label in enumerate(prefer):
                if preferred_label in metric_name:
                    score = 100 - idx
                    break

            current = picked_metrics.get(key)
            if current is None or score > current[0]:
                picked_metrics[key] = (score, metric_name)

    metric_name_to_key = {name: key for key, (_, name) in picked_metrics.items()}

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
    """
    Fetch and normalize recent annual financial metrics.
    Different data sources may return different table shapes, so we try both parsers.
    """
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
    # Financial logic: pick raw PE/PB values and avoid percentile columns from providers.
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
    # Data cleaning rule: CAGR requires strictly positive base and current values.
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

    # TODO: evaluate fiscal-year alignment instead of fixed 365.25-day approximation.
    return _dedupe_points(out)
