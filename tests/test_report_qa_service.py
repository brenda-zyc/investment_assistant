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


def test_bound_history_keeps_last_six_turns_and_merges_older_turns_into_summary() -> None:
    """Older turns should be compressed into the carried summary once the raw window is full."""
    history = [
        {"role": "user", "content": "q0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]

    trimmed_history, updated_summary = report_qa_service.bound_history(history, "older summary")

    assert len(trimmed_history) == 6
    assert trimmed_history[0]["content"] == "q1"
    assert trimmed_history[-1]["content"] == "a3"
    assert "older summary" in updated_summary
    assert "q0" in updated_summary
    assert "a0" in updated_summary


def test_answer_report_question_returns_rule_fallback_without_llm() -> None:
    """When LLM usage is disabled, the service should return a constrained fallback answer."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [{"question": "净利润是否可持续？", "summary": "收入和利润增长稳健。", "evidence": ["e1"]}],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="净利润可持续吗？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["session_key"] == "000333|https://example.com/report.pdf"
    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"]
    assert payload["evidence"]
    assert payload["confidence"] in {"medium", "low"}
    assert payload["updated_session_summary"] == ""
    assert payload["session_reset"] is False
    assert payload["citations"] == []


def test_answer_report_question_raises_for_missing_cached_context() -> None:
    """Answering without cached report context should fail fast."""
    report_qa_service.clear_report_context_cache()

    try:
        report_qa_service.answer_report_question(
            symbol="000333",
            report_key="000333|https://example.com/report.pdf",
            question="净利润可持续吗？",
            history=[],
            session_summary="",
            use_llm=False,
        )
    except ValueError as exc:
        assert "Active report context not found" in str(exc)
    else:  # pragma: no cover - defensive branch for the expected failure path
        raise AssertionError("expected ValueError")


def test_answer_report_question_falls_back_to_rule_fallback_when_llm_wrapper_raises(monkeypatch) -> None:
    """LLM failures should degrade to the same constrained fallback response path."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [{"question": "净利润是否可持续？", "summary": "收入和利润增长稳健。", "evidence": ["e1"]}],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def raise_llm(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", raise_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="净利润可持续吗？",
        history=[],
        session_summary="prior summary",
        use_llm=True,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["session_key"] == "000333|https://example.com/report.pdf"
    assert payload["updated_session_summary"]
    assert "prior summary" in payload["updated_session_summary"]


def test_answer_report_question_returns_llm_hybrid_when_llm_wrapper_succeeds(monkeypatch) -> None:
    """Successful LLM answers should be surfaced as hybrid report Q&A output."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [{"question": "净利润是否可持续？", "summary": "收入和利润增长稳健。", "evidence": ["e1"]}],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        assert kwargs["question"] == "净利润可持续吗？"
        assert kwargs["session_summary"] == "prior summary"
        return {
            "short_answer": "llm answer",
            "evidence": ["e1"],
            "citations": [{"source": "report_text", "snippet": "海外收入同比增长"}],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="净利润可持续吗？",
        history=[],
        session_summary="prior summary",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "llm answer"
    assert payload["citations"]
    assert payload["session_key"] == "000333|https://example.com/report.pdf"
    assert payload["session_reset"] is False


def test_answer_report_question_rejects_generic_llm_answer_for_unmatched_question(monkeypatch) -> None:
    """Unmatched questions should stay in rule_fallback even if the LLM returns a successful generic answer."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [
                {
                    "question": "净利润是否可持续？",
                    "summary": "收入和利润增长稳健。",
                    "evidence": ["first-answer-evidence"],
                },
                {
                    "question": "现金流怎么看？",
                    "summary": "现金流改善。",
                    "evidence": ["second-answer-evidence"],
                },
            ],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        return {
            "short_answer": "This is a generic unrelated answer.",
            "evidence": ["generic evidence"],
            "citations": [{"source": "external", "snippet": "generic"}],
            "confidence": "high",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="董事会成员是谁？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "This is a generic unrelated answer."
    assert "currently loaded annual report" in payload["short_answer"]
    assert "generic evidence" not in payload["evidence"]
    assert payload["session_reset"] is False


def test_answer_report_question_uses_boundary_fallback_for_unmatched_question() -> None:
    """Unmatched questions should stay boundary-style even when llm_analysis is present."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [
                {
                    "question": "净利润是否可持续？",
                    "summary": "第一条缓存答案不应被无关问题复用。",
                    "evidence": ["first-answer-evidence"],
                },
                {
                    "question": "现金流怎么看？",
                    "summary": "第二条缓存答案。",
                    "evidence": ["second-answer-evidence"],
                },
            ],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="董事会成员是谁？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "海外业务和 ToB 业务带动增长。"
    assert "currently loaded annual report" in payload["short_answer"]
    assert "narrow the question" in payload["short_answer"].lower()
    assert "first-answer-evidence" not in payload["evidence"]
