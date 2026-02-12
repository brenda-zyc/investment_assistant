from fastapi import APIRouter, Query

from app.usecases.industry_usecase import get_industry_cycles

# API layer guideline: endpoint remains a thin adapter over industry orchestration.
router = APIRouter()


@router.get("/industry_cycles")
def industry_cycles(
    refresh: bool = Query(default=True, description="Refresh from AkShare before reading SQLite cache"),
) -> dict:
    """Return industry cycle dashboard rows with current value and 1Y/5Y percentiles."""
    return get_industry_cycles(refresh=refresh, diagnostics=True)
