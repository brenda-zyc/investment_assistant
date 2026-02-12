from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.market_data_service import fetch_realtime_quotes, normalize_stock_code
from app.usecases.market_usecase import (
    analyze_multi_symbols,
    analyze_single_symbol,
    compute_stock_metrics_payload,
    parse_symbols_input,
)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    stock_code: str


class MultiAnalyzeRequest(BaseModel):
    stock_codes: list[str]


@router.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> dict:
    """Analyze one stock symbol and return price/financial datasets."""
    try:
        symbol = normalize_stock_code(payload.stock_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return analyze_single_symbol(symbol)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/analyze-multi")
def analyze_multi(payload: MultiAnalyzeRequest) -> dict:
    """Analyze a watchlist and return latest snapshot per symbol."""
    raw_codes = payload.stock_codes or []
    if not raw_codes:
        raise HTTPException(status_code=400, detail="stock_codes cannot be empty")
    return analyze_multi_symbols(raw_codes)


@router.get("/stock_metrics")
def stock_metrics(symbol: str = Query(..., description="6-digit A-share code")) -> dict:
    """Return current value and historical percentile for stock key metrics."""
    try:
        normalized = normalize_stock_code(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return compute_stock_metrics_payload(normalized)


@router.get("/api/realtime-prices")
def realtime_prices(symbols: str = Query(..., description="Comma-separated 6-digit A-share codes")) -> dict:
    """Return realtime quote snapshot for requested symbols without database persistence."""
    try:
        normalized_symbols = parse_symbols_input(symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    quotes = fetch_realtime_quotes(normalized_symbols)
    return {"quotes": quotes}
