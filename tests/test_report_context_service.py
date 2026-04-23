from __future__ import annotations

import datetime as dt

import app.services.report_context_service as report_context_service


def test_build_report_key_prefers_document_url() -> None:
    """Document URLs should win over detail URLs when building a report key."""
    key = report_context_service.build_report_key(
        symbol="000333",
        report={
            "document_url": "https://example.com/report.pdf",
            "detail_url": "https://example.com/detail",
        },
    )

    assert key == "000333|https://example.com/report.pdf"


def test_build_report_key_falls_back_to_detail_url() -> None:
    """Detail URLs should be used when no document URL is present."""
    key = report_context_service.build_report_key(
        symbol="000333",
        report={
            "detail_url": "https://example.com/detail",
        },
    )

    assert key == "000333|https://example.com/detail"


def test_context_from_artifact_row_rebuilds_full_report_context() -> None:
    """Persisted artifact rows should round-trip back to the in-memory context shape."""
    context = report_context_service.context_from_artifact_row(
        {
            "symbol": "000333",
            "title": "2025年年度报告",
            "published_at": "2026-03-28 20:00:00",
            "detail_url": "https://example.com/detail",
            "document_url": "https://example.com/report.pdf",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "report_text": "annual report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [{"question": "q1", "summary": "a1"}],
            "llm_analysis": {"summary": "llm note"},
        }
    )

    assert context["symbol"] == "000333"
    assert context["report"]["published_at"] == "2026-03-28 20:00:00"
    assert context["report"]["title"] == "2025年年度报告"
    assert context["report"]["detail_url"] == "https://example.com/detail"
    assert context["report"]["document_url"] == "https://example.com/report.pdf"
    assert context["report"]["content_type"] == "application/pdf"
    assert context["report"]["pdf_pages"] == 188
    assert context["report_text"] == "annual report text"
    assert context["extracted_metrics"] == {"revenue": 100.0}
    assert context["answers"] == [{"question": "q1", "summary": "a1"}]
    assert context["llm_analysis"] == {"summary": "llm note"}


def test_artifact_row_from_context_appends_extraction_version_sets_default_mode_and_parsed_at() -> None:
    """Artifact rows should record versioned metrics, the current mode, and a stable timestamp."""
    now = dt.datetime(2026, 4, 11, 15, 0, 0, tzinfo=dt.UTC)
    row = report_context_service.artifact_row_from_context(
        symbol="000333",
        report={
            "title": "2025年年度报告",
            "published_at": "2026-03-28 20:00:00",
            "detail_url": "https://example.com/detail",
            "document_url": "https://example.com/report.pdf",
            "content_type": "application/pdf",
            "pdf_pages": 188,
        },
        report_text="annual report text",
        extracted_metrics={"revenue": 100.0},
        answers=[{"question": "q1", "summary": "a1"}],
        llm_analysis={"summary": "llm note"},
        extraction_version=2,
        now=now,
    )

    assert row is not None
    assert row["report_key"] == "000333|https://example.com/report.pdf"
    assert row["title"] == "2025年年度报告"
    assert row["published_at"] == "2026-03-28 20:00:00"
    assert row["detail_url"] == "https://example.com/detail"
    assert row["document_url"] == "https://example.com/report.pdf"
    assert row["content_type"] == "application/pdf"
    assert row["pdf_pages"] == 188
    assert row["report_text"] == "annual report text"
    assert row["extracted_metrics"] == {
        "revenue": 100.0,
        "extraction_version": 2,
    }
    assert row["answers"] == [{"question": "q1", "summary": "a1"}]
    assert row["llm_analysis"] == {"summary": "llm note"}
    assert row["current_mode"] == report_context_service.REPORT_TEXT_EXTRACTED_MODE
    assert row["parsed_at"] == "2026-04-11T15:00:00+00:00"


def test_context_to_artifact_row_sets_historical_fallback_mode() -> None:
    """Historical fallback rows should use the dedicated mode constant."""
    row = report_context_service.context_to_artifact_row(
        symbol="000333",
        report={
            "document_url": "https://example.com/report.pdf",
        },
        report_text="annual report text",
        extracted_metrics={"revenue": 100.0},
        answers=[],
        llm_analysis=None,
        extraction_version=2,
        is_historical_fallback=True,
    )

    assert row is not None
    assert row["current_mode"] == report_context_service.HISTORICAL_FALLBACK_MODE
