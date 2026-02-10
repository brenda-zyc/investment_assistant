from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.data_service import (
    fetch_financial_summary,
    fetch_price_data,
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


class AnalyzeRequest(BaseModel):
    stock_code: str


class MultiAnalyzeRequest(BaseModel):
    stock_codes: list[str]


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signal_from_percentile(percentile: int) -> tuple[str, str]:
    if percentile < 20:
        return ("Undervalued", "green")
    if percentile <= 60:
        return ("Neutral", "yellow")
    return ("Expensive", "red")


def _compute_macro_signals(rows: list[dict]) -> list[dict]:
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

        less_or_equal_count = sum(1 for value in series if value <= latest_value)
        percentile = int(round((less_or_equal_count / len(series)) * 100))
        percentile = max(0, min(100, percentile))
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
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


def _analyze_symbol(symbol: str) -> dict:
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
            results.append(
                {
                    "symbol": symbol,
                    "latest_price": latest_price,
                    "latest_financial": latest_financial,
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
    rows = fetch_macro_indicators(table_name=table, limit=limit)
    return {"table": table, "rows": rows}


@app.get("/macro_signals")
def macro_signals(
    table: Literal["macro_indicators", "macro_indicators_step1", "macro_indicators_step2"] = "macro_indicators",
) -> list[dict]:
    rows = fetch_macro_indicators_all(table_name=table)
    return _compute_macro_signals(rows)
