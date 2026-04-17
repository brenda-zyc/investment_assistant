from __future__ import annotations

import datetime as dt
from typing import Any

REPORT_TEXT_EXTRACTED_MODE = "report_text_extracted"
HISTORICAL_FALLBACK_MODE = "historical_fallback"
__all__ = [
    "REPORT_TEXT_EXTRACTED_MODE",
    "HISTORICAL_FALLBACK_MODE",
    "build_report_key",
    "context_from_artifact_row",
    "artifact_row_from_context",
    "artifact_row_to_context",
    "context_to_artifact_row",
]


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    """Build a stable report key from a symbol and report source URL."""
    symbol_text = str(symbol or "").strip()
    if not symbol_text or not report:
        return None

    source_url = report.get("document_url") or report.get("detail_url")
    source_text = str(source_url or "").strip()
    if not source_text:
        return None
    return f"{symbol_text}|{source_text}"


def artifact_row_to_context(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialize one persisted report artifact payload into the shared in-memory context shape."""
    return {
        "symbol": row.get("symbol"),
        "report": {
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "detail_url": row.get("detail_url"),
            "document_url": row.get("document_url"),
            "content_type": row.get("content_type"),
            "pdf_pages": row.get("pdf_pages"),
        },
        "report_text": row.get("report_text"),
        "extracted_metrics": row.get("extracted_metrics") or {},
        "answers": row.get("answers") or [],
        "llm_analysis": row.get("llm_analysis"),
    }

def context_to_artifact_row(
    *,
    symbol: str | None,
    report: dict[str, Any] | None,
    report_text: str | None,
    extracted_metrics: dict[str, Any] | None,
    answers: list[dict[str, Any]] | None,
    llm_analysis: dict[str, Any] | None = None,
    extraction_version: int = 2,
    is_historical_fallback: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Serialize the shared in-memory report context into the persisted artifact payload shape."""
    if not symbol or not report_text:
        return None

    report_key = build_report_key(symbol, report)
    if not report_key:
        return None

    parsed_at_now = now or dt.datetime.now(dt.UTC)
    return {
        "report_key": report_key,
        "symbol": symbol,
        "document_url": (report or {}).get("document_url"),
        "detail_url": (report or {}).get("detail_url"),
        "title": (report or {}).get("title"),
        "published_at": (report or {}).get("published_at"),
        "content_type": (report or {}).get("content_type"),
        "pdf_pages": (report or {}).get("pdf_pages"),
        "report_text": report_text,
        "extracted_metrics": {
            **(extracted_metrics or {}),
            "extraction_version": extraction_version,
        },
        "answers": answers or [],
        "llm_analysis": llm_analysis,
        "current_mode": HISTORICAL_FALLBACK_MODE if is_historical_fallback else REPORT_TEXT_EXTRACTED_MODE,
        "parsed_at": parsed_at_now.isoformat(timespec="seconds"),
    }


# Legacy transition aliases for callers not yet migrated.
context_from_artifact_row = artifact_row_to_context
artifact_row_from_context = context_to_artifact_row
