from pathlib import Path
import datetime as dt
from typing import Literal
import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.services.financial_report_service import (
    extract_financial_row_from_report_text,
    fetch_report_text_from_url,
)
from app.services.industry_data_service import (
    fetch_industry_price_rows_with_diagnostics,
    get_industry_indicator_specs,
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
from app.core_logic import (
    compute_financial_report_analysis,
    compute_latest_close_percentile,
    compute_macro_signals,
    compute_stock_metrics,
    to_float,
)
from app.db import (
    fetch_industry_prices,
    fetch_macro_indicators_all,
    fetch_macro_indicators,
    fetch_financial_reports,
    fetch_stock_prices,
    init_db,
    upsert_industry_prices,
    upsert_financial_reports,
    upsert_stock_prices,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="A-share Investment Analysis")
logger = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    stock_code: str


class MultiAnalyzeRequest(BaseModel):
    stock_codes: list[str]


class FinancialReportUrlRequest(BaseModel):
    url: str


def _parse_symbols_input(symbols_text: str) -> list[str]:
    """Parse comma-separated symbols and return normalized unique 6-digit codes."""
    raw_parts = [part.strip() for part in symbols_text.split(",") if part.strip()]
    unique_symbols: list[str] = []
    for part in raw_parts:
        normalized = normalize_stock_code(part)
        if normalized not in unique_symbols:
            unique_symbols.append(normalized)
    return unique_symbols


def _compute_latest_close_percentile(price_rows: list[dict]) -> int | None:
    """Compute percentile of latest close within stored close history."""
    return compute_latest_close_percentile(price_rows)

def _compute_stock_metrics(symbol: str) -> dict:
    """Build stock metric payload with value/percentile and sampling metadata."""

    def _warn(kind: str, stock_symbol: str, exc: Exception) -> None:
        """Bridge core warnings into structured logger output."""
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

def _to_float(value: object) -> float | None:
    """Convert raw value into float when possible."""
    return to_float(value)

def _compute_macro_signals(rows: list[dict]) -> list[dict]:
    """Compute percentile-based macro signals using full available history."""
    return compute_macro_signals(rows)


def _parse_iso_date(value: object) -> dt.date | None:
    """Parse ISO-like date text to date object and return None on invalid input."""
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _compute_window_percentile(
    points: list[tuple[dt.date, float]],
    latest_date: dt.date,
    latest_value: float,
    window_days: int,
) -> tuple[int | None, int]:
    """Compute percentile of latest value inside a lookback window."""
    window_start = latest_date - dt.timedelta(days=window_days)
    window_values = [value for date_value, value in points if date_value >= window_start]
    if not window_values:
        return None, 0
    # Percentile logic: rank latest observation versus values in the same window.
    rank_le = sum(1 for value in window_values if value <= latest_value)
    percentile = int(round((rank_le / len(window_values)) * 100))
    return max(0, min(100, percentile)), len(window_values)


def _build_industry_cycles_payload(rows: list[dict], diagnostics: dict | None = None) -> dict:
    """Build current value plus 1Y/5Y percentile payload for industry indicators."""
    grouped_points: dict[str, list[tuple[dt.date, float]]] = {}
    grouped_meta: dict[str, dict[str, str]] = {}
    diagnostics = diagnostics or {}
    indicator_status_map: dict[str, dict] = diagnostics.get("indicator_status", {}) or {}

    for row in rows:
        indicator_key = str(row.get("indicator") or "").strip()
        if not indicator_key:
            continue
        trade_date = _parse_iso_date(row.get("trade_date"))
        value = _to_float(row.get("value"))
        # Data cleaning rule: ignore malformed date/value rows before percentile calculations.
        if trade_date is None or value is None:
            continue
        grouped_points.setdefault(indicator_key, []).append((trade_date, value))
        grouped_meta[indicator_key] = {
            "industry": str(row.get("industry") or ""),
            "source": str(row.get("source") or ""),
        }

    for key in grouped_points:
        grouped_points[key].sort(key=lambda item: item[0])

    output_rows: list[dict] = []
    grouped_output_rows: dict[str, list[dict]] = {}
    as_of_candidates: list[str] = []
    for spec in get_industry_indicator_specs():
        indicator_key = spec["indicator_key"]
        points = grouped_points.get(indicator_key, [])
        if not points:
            status_item = indicator_status_map.get(indicator_key, {})
            row_payload = (
                {
                    "industry": spec["industry"],
                    "indicator": spec["indicator"],
                    "value": None,
                    "1y_percentile": None,
                    "5y_percentile": None,
                    "as_of": None,
                    "source": None,
                    "status": status_item.get("status") or "no_data",
                    "error": status_item.get("error"),
                }
            )
            output_rows.append(row_payload)
            grouped_output_rows.setdefault(spec["industry"], []).append(row_payload)
            continue

        latest_date, latest_value = points[-1]
        p1y, _ = _compute_window_percentile(points, latest_date, latest_value, window_days=365)
        p5y, _ = _compute_window_percentile(points, latest_date, latest_value, window_days=365 * 5)
        as_of_text = latest_date.isoformat()
        as_of_candidates.append(as_of_text)
        status_item = indicator_status_map.get(indicator_key, {})
        row_payload = (
            {
                "industry": spec["industry"],
                "indicator": spec["indicator"],
                "value": latest_value,
                "1y_percentile": p1y,
                "5y_percentile": p5y,
                "as_of": as_of_text,
                "source": grouped_meta.get(indicator_key, {}).get("source") or None,
                "status": status_item.get("status") or "ok",
                "error": status_item.get("error"),
            }
        )
        output_rows.append(row_payload)
        grouped_output_rows.setdefault(spec["industry"], []).append(row_payload)

    industry_groups: list[dict] = []
    seen_industries: set[str] = set()
    for spec in get_industry_indicator_specs():
        industry = spec["industry"]
        if industry in seen_industries:
            continue
        seen_industries.add(industry)
        industry_groups.append(
            {
                "industry": industry,
                "rows": grouped_output_rows.get(industry, []),
            }
        )

    return {
        "as_of": max(as_of_candidates) if as_of_candidates else None,
        "rows": output_rows,
        "groups": industry_groups,
        "dns": diagnostics.get("dns") or {},
    }


def _suggest_industry_refresh_start(rows: list[dict]) -> str:
    """Suggest bounded incremental refresh start date to keep API latency predictable."""
    parsed_dates = [_parse_iso_date(row.get("trade_date")) for row in rows]
    valid_dates = [date_value for date_value in parsed_dates if date_value is not None]
    if not valid_dates:
        return (dt.date.today() - dt.timedelta(days=120)).strftime("%Y%m%d")
    # API assumption: backfill overlap avoids gaps when upstream sources revise recent points.
    return (max(valid_dates) - dt.timedelta(days=30)).strftime("%Y%m%d")


def _industry_history_is_sparse(rows: list[dict], min_points_per_indicator: int = 12) -> bool:
    """Return True when one or more indicators have too few cached points."""
    counts: dict[str, int] = {}
    for row in rows:
        indicator = str(row.get("indicator") or "").strip()
        if not indicator:
            continue
        value = _to_float(row.get("value"))
        if value is None:
            continue
        counts[indicator] = counts.get(indicator, 0) + 1

    for spec in get_industry_indicator_specs():
        indicator_key = spec["indicator_key"]
        if counts.get(indicator_key, 0) < min_points_per_indicator:
            return True
    return False

@app.on_event("startup")
def on_startup() -> None:
    """Initialize local storage on service startup."""
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the single-page dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})


def _analyze_symbol(symbol: str) -> dict:
    """Fetch and persist single-symbol data with cache fallback warnings."""
    warnings: list[str] = []

    try:
        price_rows = fetch_price_data(symbol)
        upsert_stock_prices(symbol, price_rows)
        stored_prices = fetch_stock_prices(symbol)
    except Exception as exc:
        stored_prices = fetch_stock_prices(symbol)
        if stored_prices:
            warnings.append(f"Price fetch failed; returned cached data. Reason: {exc}")
        else:
            warnings.append(f"Price fetch failed; no cache available. Returned empty price data. Reason: {exc}")
            stored_prices = []

    try:
        financial_rows = fetch_financial_summary(symbol)
        upsert_financial_reports(symbol, financial_rows)
        stored_financials = fetch_financial_reports(symbol)
    except Exception as exc:
        stored_financials = fetch_financial_reports(symbol)
        if stored_financials:
            warnings.append(f"Financial fetch failed; returned cached data. Reason: {exc}")
        else:
            warnings.append(
                f"Financial fetch failed; no cache available. Returned empty financial data. Reason: {exc}"
            )
            stored_financials = []

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([symbol]).get(symbol) or None
    except Exception as exc:
        warnings.append(f"Stock name fetch failed. Reason: {exc}")

    # API assumption: realtime feed can fail independently from historical data pipeline.
    try:
        realtime_quote = fetch_realtime_quotes([symbol]).get(symbol, {})
    except Exception as exc:
        warnings.append(f"Realtime quote fetch failed; using historical latest close. Reason: {exc}")
        realtime_quote = {}
    if realtime_quote.get("name"):
        symbol_name = realtime_quote["name"]
    return {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "realtime": realtime_quote if realtime_quote else None,
        "price_data": stored_prices,
        "financial_summary": stored_financials,
        "warnings": warnings,
    }


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> dict:
    """Analyze one stock symbol and return price/financial datasets."""
    try:
        symbol = normalize_stock_code(payload.stock_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return _analyze_symbol(symbol)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze-multi")
def analyze_multi(payload: MultiAnalyzeRequest) -> dict:
    """Analyze a watchlist and return latest snapshot per symbol."""
    raw_codes = payload.stock_codes or []
    if not raw_codes:
        raise HTTPException(status_code=400, detail="stock_codes cannot be empty")

    unique_codes: list[str] = []
    for code in raw_codes:
        if code not in unique_codes:
            unique_codes.append(code)

    results: list[dict] = []
    successful_symbols: list[str] = []
    for raw_code in unique_codes[:20]:
        try:
            symbol = normalize_stock_code(raw_code)
        except ValueError as exc:
            results.append({"symbol": raw_code, "error": str(exc)})
            continue

        try:
            analyzed = _analyze_symbol(symbol)
            latest_price = analyzed["price_data"][0] if analyzed["price_data"] else None
            latest_financial = (
                analyzed["financial_summary"][0] if analyzed["financial_summary"] else None
            )
            close_percentile = _compute_latest_close_percentile(analyzed["price_data"])
            results.append(
                {
                    "symbol": symbol,
                    "symbol_name": None,
                    "latest_price": latest_price,
                    "latest_financial": latest_financial,
                    "close_percentile": close_percentile,
                    "realtime": None,
                    "warnings": analyzed["warnings"],
                }
            )
            successful_symbols.append(symbol)
        except RuntimeError as exc:
            results.append({"symbol": symbol, "error": str(exc)})

    try:
        name_map = fetch_stock_names(successful_symbols)
    except Exception as exc:
        name_map = {}
        for item in results:
            if item.get("error"):
                continue
            item.setdefault("warnings", []).append(f"Stock name fetch failed. Reason: {exc}")

    for item in results:
        if item.get("error"):
            continue
        item["symbol_name"] = name_map.get(item["symbol"]) or None

    try:
        realtime_map = fetch_realtime_quotes(successful_symbols)
    except Exception as exc:
        realtime_map = {}
        for item in results:
            if item.get("error"):
                continue
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
        # Do not persist realtime data; only update response snapshot for UI freshness.
        if quote.get("latest_price") is not None:
            latest_price = dict(item.get("latest_price") or {})
            latest_price["close"] = quote["latest_price"]
            if quote.get("updated_at"):
                latest_price["trade_date"] = str(quote["updated_at"])
            item["latest_price"] = latest_price

    return {"results": results}


@app.get("/api/macro-indicators")
def macro_indicators(
    table: Literal["macro_indicators", "macro_indicators_step1", "macro_indicators_step2"] = "macro_indicators",
    limit: int = Query(default=30, ge=1, le=500),
) -> dict:
    """Return recent macro indicator rows from the selected table."""
    rows = fetch_macro_indicators(table_name=table, limit=limit)
    return {"table": table, "rows": rows}


@app.get("/macro_signals")
def macro_signals(
    table: Literal["macro_indicators", "macro_indicators_step1", "macro_indicators_step2"] = "macro_indicators",
) -> list[dict]:
    """Return latest percentile-based macro signals."""
    rows = fetch_macro_indicators_all(table_name=table)
    return _compute_macro_signals(rows)


@app.get("/stock_metrics")
def stock_metrics(symbol: str = Query(..., description="6-digit A-share code")) -> dict:
    """Return current value and historical percentile for stock key metrics."""
    # TODO: add optional lookback window parameter for scenario analysis.
    try:
        normalized = normalize_stock_code(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _compute_stock_metrics(normalized)


@app.get("/api/realtime-prices")
def realtime_prices(symbols: str = Query(..., description="Comma-separated 6-digit A-share codes")) -> dict:
    """Return realtime quote snapshot for requested symbols without database persistence."""
    try:
        normalized_symbols = _parse_symbols_input(symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    quotes = fetch_realtime_quotes(normalized_symbols)
    return {"quotes": quotes}


@app.get("/industry_cycles")
def industry_cycles(
    refresh: bool = Query(default=True, description="Refresh from AkShare before reading SQLite cache"),
) -> dict:
    """Return industry cycle dashboard rows with current value and 1Y/5Y percentiles."""
    warnings: list[str] = []
    diagnostics: dict = {}
    existing_rows = fetch_industry_prices()
    if refresh:
        try:
            # API assumption: upstream endpoints can fail; cached table remains the fallback source.
            if _industry_history_is_sparse(existing_rows):
                # Financial logic: use longer backfill when indicators are missing to avoid persistent blanks.
                start_date = (dt.date.today() - dt.timedelta(days=365 * 3)).strftime("%Y%m%d")
                warnings.append("Industry cache sparse; triggered extended backfill window.")
            else:
                start_date = _suggest_industry_refresh_start(existing_rows)
            fetched_rows, diagnostics = fetch_industry_price_rows_with_diagnostics(start_date=start_date)
            if fetched_rows:
                upsert_industry_prices(fetched_rows)
            else:
                warnings.append("Industry data fetch returned 0 rows; using existing cache.")
        except Exception as exc:
            warnings.append(f"Industry data fetch failed; using existing cache. Reason: {exc}")

    history_rows = fetch_industry_prices()
    payload = _build_industry_cycles_payload(history_rows, diagnostics=diagnostics)
    payload["warnings"] = warnings
    # TODO: add optional per-indicator refresh flag to reduce network pressure.
    return payload


@app.get("/api/financial-report-analysis")
def financial_report_analysis(symbol: str = Query(..., description="6-digit A-share code")) -> dict:
    """Return normalized annual financial reports and auto-generated analysis insights."""
    try:
        normalized = normalize_stock_code(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    warnings: list[str] = []
    try:
        financial_rows = fetch_financial_summary(normalized)
        upsert_financial_reports(normalized, financial_rows)
        stored_financial_rows = fetch_financial_reports(normalized)
    except Exception as exc:
        stored_financial_rows = fetch_financial_reports(normalized)
        if stored_financial_rows:
            warnings.append(f"Financial fetch failed; returned cached data. Reason: {exc}")
        else:
            warnings.append(
                f"Financial fetch failed; no cache available. Returned empty financial data. Reason: {exc}"
            )
            stored_financial_rows = []

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([normalized]).get(normalized) or None
    except Exception as exc:
        warnings.append(f"Stock name fetch failed. Reason: {exc}")

    analysis_payload = compute_financial_report_analysis(stored_financial_rows)
    analysis_payload["symbol"] = normalized
    analysis_payload["symbol_name"] = symbol_name
    analysis_payload["warnings"] = warnings
    return analysis_payload


@app.post("/api/financial-report-url-analysis")
def financial_report_url_analysis(payload: FinancialReportUrlRequest) -> dict:
    """Analyze a Chinese financial report web link and return extracted metrics."""
    try:
        fetched = fetch_report_text_from_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/runtime variability
        raise HTTPException(status_code=502, detail=f"Could not retrieve report URL content: {exc}") from exc

    extracted = extract_financial_row_from_report_text(fetched["text"], title=fetched.get("title"))
    report_year = extracted.get("report_year")
    report_date = extracted.get("report_date")
    if report_year is None and report_date:
        report_year = int(str(report_date)[:4])
    if report_year is None:
        report_year = dt.date.today().year
        extracted["warnings"] = [*extracted.get("warnings", []), "Used current year as fallback report_year."]
    if not report_date:
        report_date = f"{report_year}-12-31"

    row = {
        "report_year": report_year,
        "report_date": report_date,
        "revenue": extracted.get("revenue"),
        "net_profit": extracted.get("net_profit"),
        "roe": extracted.get("roe"),
        "debt_ratio": extracted.get("debt_ratio"),
    }
    analysis_payload = compute_financial_report_analysis([row])
    if extracted.get("warnings"):
        analysis_payload["highlights"] = [
            {
                "level": "warn",
                "title": "Parsing notes",
                "detail": " | ".join(extracted["warnings"]),
            },
            *analysis_payload.get("highlights", []),
        ]
    if fetched.get("tls_insecure"):
        analysis_payload["highlights"] = [
            {
                "level": "warn",
                "title": "TLS warning",
                "detail": "TLS verification was bypassed via REPORT_URL_INSECURE_SSL=1. Use only in trusted networks.",
            },
            *analysis_payload.get("highlights", []),
        ]

    return {
        "source_url": fetched["url"],
        "source_title": fetched.get("title"),
        "content_type": fetched.get("content_type"),
        "pdf_pages": fetched.get("pdf_pages"),
        "tls_insecure": fetched.get("tls_insecure"),
        "analysis": analysis_payload,
        "extracted": extracted,
    }
