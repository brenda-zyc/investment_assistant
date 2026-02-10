from pathlib import Path
from typing import Literal
import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.data_service import (
    build_revenue_cagr_5y_series,
    fetch_financial_metric_series,
    fetch_financial_summary,
    fetch_price_data,
    fetch_valuation_series,
    normalize_stock_code,
)
from app.db import (
    fetch_macro_indicators_all,
    fetch_macro_indicators,
    fetch_financial_reports,
    fetch_stock_prices,
    init_db,
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


def _compute_latest_close_percentile(price_rows: list[dict]) -> int | None:
    """Compute percentile of latest close within stored close history."""
    if not price_rows:
        return None

    closes: list[float] = []
    latest_close: float | None = None
    for row in price_rows:
        value = _to_float(row.get("close"))
        if value is None:
            continue
        closes.append(value)
        if latest_close is None:
            latest_close = value

    if latest_close is None or len(closes) < 2:
        return None

    rank_le = sum(1 for value in closes if value <= latest_close)
    percentile = int(round((rank_le / len(closes)) * 100))
    return max(0, min(100, percentile))


def _compute_percentile_from_points(points: list[tuple[str, float]], min_samples: int = 24) -> dict:
    """Compute latest-value percentile within a metric's historical series."""
    # Data cleaning rule: ignore null values before percentile ranking.
    cleaned = [(d, v) for d, v in points if v is not None]
    if not cleaned:
        return {"value": None, "percentile": None, "as_of": None, "data_insufficient": True, "sample_size": 0}

    latest_date, latest_value = cleaned[-1]
    series_values = [v for _, v in cleaned]
    sample_size = len(series_values)
    if sample_size < min_samples:
        return {
            "value": latest_value,
            "percentile": None,
            "as_of": latest_date,
            "data_insufficient": True,
            "sample_size": sample_size,
        }

    # Percentile logic: rank latest observation in its own historical distribution.
    rank_le = sum(1 for value in series_values if value <= latest_value)
    percentile = int(round((rank_le / sample_size) * 100))
    percentile = max(0, min(100, percentile))
    return {
        "value": latest_value,
        "percentile": percentile,
        "as_of": latest_date,
        "data_insufficient": False,
        "sample_size": sample_size,
    }


def _compute_stock_metrics(symbol: str) -> dict:
    """Build stock metric payload with value/percentile and sampling metadata."""
    # API assumption: upstream AkShare endpoints can fail independently.
    try:
        valuation_series = fetch_valuation_series(symbol)
    except Exception as exc:
        logger.warning("stock_metrics valuation fetch failed symbol=%s err=%s", symbol, exc)
        valuation_series = {"pe_ttm": [], "pb": []}

    try:
        fin_series = fetch_financial_metric_series(symbol)
    except Exception as exc:
        logger.warning("stock_metrics financial fetch failed symbol=%s err=%s", symbol, exc)
        fin_series = {"roe": [], "roic": [], "revenue": []}

    # Financial logic: CAGR is derived from revenue history, not fetched directly.
    revenue_cagr_series = build_revenue_cagr_5y_series(fin_series.get("revenue", []))

    metric_sources = {
        "pe_ttm": valuation_series.get("pe_ttm", []),
        "pb": valuation_series.get("pb", []),
        "roe": fin_series.get("roe", []),
        "roic": fin_series.get("roic", []),
        "revenue_cagr_5y": revenue_cagr_series,
    }
    metric_units = {
        "pe_ttm": "",
        "pb": "",
        "roe": "ratio",
        "roic": "ratio",
        "revenue_cagr_5y": "ratio",
    }

    metrics_payload: list[dict] = []
    as_of_dates: list[str] = []
    for metric_name, points in metric_sources.items():
        logger.info("stock_metrics metric=%s symbol=%s points=%d", metric_name, symbol, len(points))
        computed = _compute_percentile_from_points(points, min_samples=24)
        if computed["as_of"]:
            as_of_dates.append(computed["as_of"])
        metrics_payload.append(
            {
                "name": metric_name,
                "value": computed["value"],
                "percentile": computed["percentile"],
                "unit": metric_units[metric_name],
                "data_insufficient": computed["data_insufficient"],
                "sample_size": computed["sample_size"],
            }
        )

    return {
        "symbol": symbol,
        "as_of": max(as_of_dates) if as_of_dates else None,
        "metrics": metrics_payload,
    }


def _to_float(value: object) -> float | None:
    """Convert raw value into float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signal_from_percentile(percentile: int) -> tuple[str, str]:
    """Map percentile to valuation-style signal label and color."""
    if percentile < 20:
        return ("Undervalued", "green")
    if percentile <= 60:
        return ("Neutral", "yellow")
    return ("Expensive", "red")


def _compute_macro_signals(rows: list[dict]) -> list[dict]:
    """Compute percentile-based macro signals using full available history."""
    if not rows:
        return []

    indicators = [key for key in rows[0].keys() if key != "date"]
    signals: list[dict] = []

    for indicator in indicators:
        latest_value: float | None = None
        series: list[float] = []

        for row in rows:
            value = _to_float(row.get(indicator))
            if value is not None:
                series.append(value)
                if latest_value is None:
                    latest_value = value

        if latest_value is None or not series:
            continue

        # Percentile logic: compare latest value against the metric's own history.
        less_or_equal_count = sum(1 for value in series if value <= latest_value)
        percentile = int(round((less_or_equal_count / len(series)) * 100))
        percentile = max(0, min(100, percentile))
        # Financial rule override: PMI uses an economic threshold, not valuation buckets.
        if indicator == "china_pmi":
            if latest_value >= 50:
                signal_label, signal_color = ("Expansion", "green")
            else:
                signal_label, signal_color = ("Contraction", "red")
        else:
            signal_label, signal_color = _signal_from_percentile(percentile)

        signals.append(
            {
                "indicator": indicator,
                "value": latest_value,
                "percentile": percentile,
                "signal_label": signal_label,
                "signal_color": signal_color,
            }
        )

    return sorted(signals, key=lambda item: item["indicator"])


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

    return {
        "symbol": symbol,
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
                    "latest_price": latest_price,
                    "latest_financial": latest_financial,
                    "close_percentile": close_percentile,
                    "warnings": analyzed["warnings"],
                }
            )
        except RuntimeError as exc:
            results.append({"symbol": symbol, "error": str(exc)})

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
