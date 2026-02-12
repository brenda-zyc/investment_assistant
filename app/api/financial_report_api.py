from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.market_data_service import normalize_stock_code
from app.usecases.financial_report_usecase import (
    analyze_financial_report_url,
    get_financial_report_analysis,
)

# API layer guideline: keep exception-to-HTTP mapping centralized in route functions.
router = APIRouter()


class FinancialReportUrlRequest(BaseModel):
    url: str


@router.get("/api/financial-report-analysis")
def financial_report_analysis(symbol: str = Query(..., description="6-digit A-share code")) -> dict:
    """Return normalized annual financial reports and auto-generated analysis insights."""
    try:
        normalized = normalize_stock_code(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_financial_report_analysis(normalized)


@router.post("/api/financial-report-url-analysis")
def financial_report_url_analysis(payload: FinancialReportUrlRequest) -> dict:
    """Analyze a Chinese financial report web link and return extracted metrics."""
    try:
        return analyze_financial_report_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # API assumption: parsing/runtime report issues are treated as unprocessable content.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/runtime variability
        raise HTTPException(status_code=502, detail=f"Could not retrieve report URL content: {exc}") from exc
