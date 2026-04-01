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


def test_store_report_context_keeps_nested_input_mutations_out_of_cache() -> None:
    """Nested caller mutations after storage should not leak into the cache."""
    report_qa_service.clear_report_context_cache()
    report_key = "000333|https://example.com/report.pdf"
    context = {
        "symbol": "000333",
        "report": {
            "document_url": "https://example.com/report.pdf",
            "metadata": {"title": "2024年年度报告"},
        },
        "report_text": "annual report text",
        "answers": [{"question": "q1", "evidence": ["line 1"]}],
    }

    report_qa_service.store_report_context(report_key, context)
    context["report"]["metadata"]["title"] = "changed"
    context["answers"][0]["evidence"].append("line 2")

    cached = report_qa_service.get_cached_report_context(report_key)

    assert cached is not None
    assert cached["report"]["metadata"]["title"] == "2024年年度报告"
    assert cached["answers"][0]["evidence"] == ["line 1"]


def test_get_cached_report_context_returns_deep_copy() -> None:
    """Mutating nested data from a cached read should not leak back into the cache."""
    report_qa_service.clear_report_context_cache()
    report_key = "000333|https://example.com/report.pdf"
    report_qa_service.store_report_context(
        report_key,
        {
            "symbol": "000333",
            "report": {"document_url": "https://example.com/report.pdf"},
            "report_text": "annual report text",
            "answers": [{"question": "q1", "evidence": ["line 1"]}],
        },
    )

    cached = report_qa_service.get_cached_report_context(report_key)
    assert cached is not None
    cached["report"]["document_url"] = "https://example.com/changed.pdf"
    cached["answers"][0]["evidence"].append("line 2")

    reread = report_qa_service.get_cached_report_context(report_key)
    assert reread is not None
    assert reread["report"]["document_url"] == "https://example.com/report.pdf"
    assert reread["answers"][0]["evidence"] == ["line 1"]


def test_store_report_context_refreshes_existing_key_before_eviction() -> None:
    """Re-storing a key should make it count as the newest cache entry."""
    report_qa_service.clear_report_context_cache()
    limit = report_qa_service.REPORT_CONTEXT_CACHE_MAX_ENTRIES

    for idx in range(limit):
        report_qa_service.store_report_context(
            f"000{idx:03d}|https://example.com/report-{idx}.pdf",
            {
                "symbol": f"000{idx:03d}",
                "report": {"document_url": f"https://example.com/report-{idx}.pdf"},
                "report_text": f"text {idx}",
            },
        )

    refreshed_key = "000000|https://example.com/report-0.pdf"
    report_qa_service.store_report_context(
        refreshed_key,
        {
            "symbol": "000000",
            "report": {"document_url": "https://example.com/report-0.pdf"},
            "report_text": "refreshed text",
        },
    )
    report_qa_service.store_report_context(
        f"999999|https://example.com/report-new.pdf",
        {
            "symbol": "999999",
            "report": {"document_url": "https://example.com/report-new.pdf"},
            "report_text": "text new",
        },
    )

    assert report_qa_service.get_cached_report_context(refreshed_key) is not None
    assert report_qa_service.get_cached_report_context("000001|https://example.com/report-1.pdf") is None
