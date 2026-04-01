from __future__ import annotations

import threading
from typing import Any


_REPORT_CONTEXT_LOCK = threading.Lock()
_REPORT_CONTEXTS: dict[str, dict[str, Any]] = {}


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    """Build a stable cache key for one active report context."""
    symbol_text = str(symbol or "").strip()
    if not symbol_text or not report:
        return None

    source_url = report.get("document_url") or report.get("detail_url")
    source_text = str(source_url or "").strip()
    if not source_text:
        return None
    return f"{symbol_text}|{source_text}"


def clear_report_context_cache() -> None:
    """Remove all cached report contexts from process memory."""
    with _REPORT_CONTEXT_LOCK:
        _REPORT_CONTEXTS.clear()


def store_report_context(report_key: str, context: dict[str, Any]) -> None:
    """Store one report context as an isolated copy in process memory."""
    with _REPORT_CONTEXT_LOCK:
        _REPORT_CONTEXTS[report_key] = dict(context)


def get_cached_report_context(report_key: str) -> dict[str, Any] | None:
    """Return a copy of the cached report context for the requested key."""
    with _REPORT_CONTEXT_LOCK:
        current = _REPORT_CONTEXTS.get(report_key)
    return dict(current) if current else None
