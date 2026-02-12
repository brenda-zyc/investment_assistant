from typing import Literal

from fastapi import APIRouter, Query

from app.core_logic import compute_macro_signals
from app.db import fetch_macro_indicators, fetch_macro_indicators_all

router = APIRouter()


@router.get("/api/macro-indicators")
def macro_indicators(
    table: Literal["macro_indicators", "macro_indicators_step1", "macro_indicators_step2"] = "macro_indicators",
    limit: int = Query(default=30, ge=1, le=500),
) -> dict:
    """Return recent macro indicator rows from the selected table."""
    rows = fetch_macro_indicators(table_name=table, limit=limit)
    return {"table": table, "rows": rows}


@router.get("/macro_signals")
def macro_signals(
    table: Literal["macro_indicators", "macro_indicators_step1", "macro_indicators_step2"] = "macro_indicators",
) -> list[dict]:
    """Return latest percentile-based macro signals."""
    rows = fetch_macro_indicators_all(table_name=table)
    return compute_macro_signals(rows)
