from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.llm_service import (
    get_session_llm_config_masked,
    set_session_llm_config,
    test_llm_connection,
)
from app.services.market_data_service import normalize_stock_code
from app.usecases.financial_report_usecase import (
    analyze_financial_report_url,
    autonomous_financial_report_read,
    get_financial_report_analysis,
)

# API layer guideline: keep exception-to-HTTP mapping centralized in route functions.
router = APIRouter()


class FinancialReportUrlRequest(BaseModel):
    url: str
    symbol: str | None = None


class LlmSessionConfigRequest(BaseModel):
    provider: str = "deepseek"
    base_url: str
    model: str
    api_key: str


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
    normalized_symbol: str | None = None
    if payload.symbol is not None:
        try:
            normalized_symbol = normalize_stock_code(payload.symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return analyze_financial_report_url(payload.url, symbol=normalized_symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # API assumption: parsing/runtime report issues are treated as unprocessable content.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/runtime variability
        raise HTTPException(status_code=502, detail=f"Could not retrieve report URL content: {exc}") from exc


@router.get("/api/financial-report-autoread")
def financial_report_autoread(symbol: str = Query(..., description="6-digit A-share code")) -> dict:
    """Auto-discover and analyze the latest annual report for a stock symbol."""
    try:
        normalized = normalize_stock_code(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return autonomous_financial_report_read(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/runtime variability
        raise HTTPException(status_code=502, detail=f"Could not auto-read annual report: {exc}") from exc


@router.get("/api/llm/session-config")
def llm_session_config_status() -> dict:
    """Return masked session-level LLM configuration status."""
    return get_session_llm_config_masked()


@router.post("/api/llm/session-config")
def llm_session_config_save(payload: LlmSessionConfigRequest) -> dict:
    """Save the current operator-provided LLM config into backend process memory."""
    try:
        return set_session_llm_config(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/llm/test-connection")
def llm_test_connection(payload: LlmSessionConfigRequest) -> dict:
    """Validate that the submitted LLM configuration can answer a minimal request."""
    try:
        return test_llm_connection(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/runtime variability
        raise HTTPException(status_code=502, detail=f"Could not test LLM connection: {exc}") from exc
