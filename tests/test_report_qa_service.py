from __future__ import annotations

import app.services.report_qa_service as report_qa_service


def test_build_report_key_prefers_document_url() -> None:
    """Document URLs should win over detail URLs when building a report cache key."""
    key = report_qa_service.build_report_key(
        symbol="000333",
        report={
            "document_url": "https://example.com/report.pdf",
            "detail_url": "https://example.com/detail",
        },
    )

    assert key == "000333|https://example.com/report.pdf"


def test_get_cached_report_context_returns_none_for_unknown_key() -> None:
    """Unknown cache keys should not fabricate report context."""
    report_qa_service.clear_report_context_cache()

    assert report_qa_service.get_cached_report_context("missing") is None


def test_store_report_context_keeps_a_copy_of_input_context() -> None:
    """Mutating the original context after storage should not affect cached data."""
    report_qa_service.clear_report_context_cache()
    report_key = "000333|https://example.com/report.pdf"
    context = {
        "symbol": "000333",
        "report": {"document_url": "https://example.com/report.pdf"},
        "report_text": "annual report text",
    }

    report_qa_service.store_report_context(report_key, context)
    context["symbol"] = "999999"

    cached = report_qa_service.get_cached_report_context(report_key)

    assert cached is not None
    assert cached["symbol"] == "000333"
