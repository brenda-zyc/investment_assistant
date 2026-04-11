from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from app.core_logic import compute_latest_close_percentile, compute_stock_metrics
from app.db import (
    fetch_financial_reports,
    fetch_stock_prices,
    upsert_financial_reports,
    upsert_stock_prices,
)
from app.services.market_data_service import (
    build_revenue_cagr_5y_series,
    fetch_financial_metric_series,
    fetch_financial_summary,
    fetch_price_data,
    fetch_realtime_quotes,
    fetch_stock_names,
    fetch_valuation_series,
    normalize_stock_code,
)

logger = logging.getLogger(__name__)

WATCHLIST_MAX_SYMBOLS = 20
WATCHLIST_MAX_WORKERS = 4


def _deduplicate_codes(raw_codes: list[str]) -> list[str]:
    """Return codes in first-seen order without duplicates."""
    unique_codes: list[str] = []
    for code in raw_codes:
        if code not in unique_codes:
            unique_codes.append(code)
    return unique_codes


def _attach_stock_names(results: list[dict], successful_symbols: list[str]) -> None:
    """Populate symbol names for successful rows with graceful fallback warnings."""
    try:
        name_map = fetch_stock_names(successful_symbols)
    except Exception as exc:
        name_map = {}
        for item in results:
            if item.get("error"):
                continue
            # API assumption: name endpoint failures should not fail the whole watchlist response.
            item.setdefault("warnings", []).append(f"Stock name fetch failed. Reason: {exc}")

    for item in results:
        if item.get("error"):
            continue
        item["symbol_name"] = name_map.get(item["symbol"]) or None


def _attach_realtime_snapshots(results: list[dict], successful_symbols: list[str]) -> None:
    """Merge realtime quote snapshots into existing watchlist rows."""
    try:
        realtime_map = fetch_realtime_quotes(successful_symbols)
    except Exception as exc:
        realtime_map = {}
        for item in results:
            if item.get("error"):
                continue
            # API assumption: realtime feed is optional; fallback data is acceptable.
            item.setdefault("warnings", []).append(
                f"Realtime quote fetch failed; using historical latest close. Reason: {exc}"
            )

    for item in results:
        if item.get("error"):
            continue
        symbol = item["symbol"]
        quote = realtime_map.get(symbol)
        if not quote:
            continue
        if quote.get("name"):
            item["symbol_name"] = quote["name"]
        item["realtime"] = quote
        if quote.get("latest_price") is not None:
            latest_price = dict(item.get("latest_price") or {})
            latest_price["close"] = quote["latest_price"]
            if quote.get("updated_at"):
                latest_price["trade_date"] = str(quote["updated_at"])
            item["latest_price"] = latest_price


def parse_symbols_input(symbols_text: str) -> list[str]:
    """Parse comma-separated symbols and return normalized unique 6-digit codes."""
    raw_parts = [part.strip() for part in symbols_text.split(",") if part.strip()]
    unique_symbols: list[str] = []
    for part in raw_parts:
        normalized = normalize_stock_code(part)
        if normalized not in unique_symbols:
            unique_symbols.append(normalized)
    return unique_symbols


def _fetch_cached_symbol_data(symbol: str, *, refresh: bool = False) -> dict:
    """Load cached symbol history first, refreshing upstream only when explicitly requested or empty."""
    warnings: list[str] = []
    stored_prices = fetch_stock_prices(symbol)
    stored_financials = fetch_financial_reports(symbol)

    if refresh or not stored_prices:
        try:
            price_rows = fetch_price_data(symbol)
            upsert_stock_prices(symbol, price_rows)
            stored_prices = fetch_stock_prices(symbol)
        except Exception as exc:
            if stored_prices:
                warnings.append(f"Price fetch failed; returned cached data. Reason: {exc}")
            else:
                warnings.append(
                    f"Price fetch failed; no cache available. Returned empty price data. Reason: {exc}"
                )
                stored_prices = []

    if refresh or not stored_financials:
        try:
            financial_rows = fetch_financial_summary(symbol)
            upsert_financial_reports(symbol, financial_rows)
            stored_financials = fetch_financial_reports(symbol)
        except Exception as exc:
            if stored_financials:
                warnings.append(f"Financial fetch failed; returned cached data. Reason: {exc}")
            else:
                warnings.append(
                    f"Financial fetch failed; no cache available. Returned empty financial data. Reason: {exc}"
                )
                stored_financials = []

    return {
        "price_data": stored_prices,
        "financial_summary": stored_financials,
        "warnings": warnings,
    }


def _build_watchlist_snapshot(symbol: str, *, refresh: bool = False) -> dict:
    """Build one watchlist row without realtime or stock-name enrichment."""
    analyzed = _fetch_cached_symbol_data(symbol, refresh=refresh)
    latest_price = analyzed["price_data"][0] if analyzed["price_data"] else None
    latest_financial = analyzed["financial_summary"][0] if analyzed["financial_summary"] else None
    # Percentile calculation: latest close ranked against cached close history.
    close_percentile = compute_latest_close_percentile(analyzed["price_data"])
    return {
        "symbol": symbol,
        "symbol_name": None,
        "latest_price": latest_price,
        "latest_financial": latest_financial,
        "close_percentile": close_percentile,
        "realtime": None,
        "warnings": analyzed["warnings"],
    }


def analyze_single_symbol(symbol: str, *, refresh: bool = False) -> dict:
    """Fetch and persist single-symbol data with cache fallback warnings."""
    analyzed = _fetch_cached_symbol_data(symbol, refresh=refresh)

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([symbol]).get(symbol) or None
    except Exception as exc:
        analyzed["warnings"].append(f"Stock name fetch failed. Reason: {exc}")

    try:
        realtime_quote = fetch_realtime_quotes([symbol]).get(symbol, {})
    except Exception as exc:
        # API assumption: realtime quote API can fail independently from historical datasets.
        analyzed["warnings"].append(f"Realtime quote fetch failed; using historical latest close. Reason: {exc}")
        realtime_quote = {}

    if realtime_quote.get("name"):
        symbol_name = realtime_quote["name"]

    return {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "realtime": realtime_quote if realtime_quote else None,
        "price_data": analyzed["price_data"],
        "financial_summary": analyzed["financial_summary"],
        "warnings": analyzed["warnings"],
    }


def analyze_multi_symbols(raw_codes: list[str], *, refresh: bool = False) -> dict:
    """Analyze a watchlist and return latest snapshot per symbol."""
    unique_codes = _deduplicate_codes(raw_codes)[:WATCHLIST_MAX_SYMBOLS]
    ordered_results: list[dict | None] = [None] * len(unique_codes)
    indexed_valid_symbols: list[tuple[int, str]] = []

    # API assumption: watchlist endpoint enforces an upper bound to keep latency predictable.
    for index, raw_code in enumerate(unique_codes):
        try:
            symbol = normalize_stock_code(raw_code)
        except ValueError as exc:
            ordered_results[index] = {"symbol": raw_code, "error": str(exc)}
            continue
        indexed_valid_symbols.append((index, symbol))

    if indexed_valid_symbols:
        max_workers = min(WATCHLIST_MAX_WORKERS, len(indexed_valid_symbols))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_build_watchlist_snapshot, symbol, refresh=refresh): (index, symbol)
                for index, symbol in indexed_valid_symbols
            }
            for future in as_completed(future_map):
                index, symbol = future_map[future]
                try:
                    ordered_results[index] = future.result()
                except Exception as exc:
                    ordered_results[index] = {"symbol": symbol, "error": str(exc)}

    results = [item for item in ordered_results if item is not None]
    successful_symbols = [item["symbol"] for item in results if not item.get("error")]
    _attach_stock_names(results, successful_symbols)
    _attach_realtime_snapshots(results, successful_symbols)

    return {"results": results}


def compute_stock_metrics_payload(symbol: str) -> dict:
    """Build stock metric payload with value/percentile and sampling metadata."""

    def _warn(kind: str, stock_symbol: str, exc: Exception) -> None:
        """Emit structured warnings from core metric pipeline."""
        logger.warning("stock_metrics %s fetch failed symbol=%s err=%s", kind, stock_symbol, exc)

    payload = compute_stock_metrics(
        symbol=symbol,
        fetch_valuation_series_fn=fetch_valuation_series,
        fetch_financial_metric_series_fn=fetch_financial_metric_series,
        build_revenue_cagr_5y_series_fn=build_revenue_cagr_5y_series,
        warn_fn=_warn,
    )
    for metric in payload["metrics"]:
        logger.info(
            "stock_metrics metric=%s symbol=%s sample_size=%d",
            metric["name"],
            symbol,
            metric["sample_size"],
        )
    return payload
