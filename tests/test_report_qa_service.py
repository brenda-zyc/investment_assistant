from __future__ import annotations

import logging
from typing import Any, cast

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

    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"]
    assert payload["evidence"]
    assert payload["confidence"] in {"medium", "low"}
    assert payload["updated_session_summary"] == ""
    assert payload["session_reset"] is False
    assert payload["citations"] == []


def test_answer_report_question_uses_report_context_when_llm_is_disabled_and_no_cached_answer_matches() -> None:
    """Report-scoped questions without a cached-answer match should still use report context."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "This Q&A session is limited to the currently loaded annual report. Please narrow the question to this report."
    assert payload["evidence"]
    assert payload["session_reset"] is False


def test_answer_report_question_raises_for_missing_cached_context(monkeypatch) -> None:
    """Answering without cached report context should fail fast."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(report_qa_service, "fetch_report_artifact", lambda _report_key: None)

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


def test_answer_report_question_loads_persisted_artifact_when_memory_cache_is_empty(monkeypatch) -> None:
    """Q&A should reload persisted report context when the in-memory cache is empty."""
    report_qa_service.clear_report_context_cache()
    captured: dict[str, int] = {"mapper_calls": 0}

    def fake_artifact_row_to_context(row):
        captured["mapper_calls"] += 1
        assert row["document_url"] == "https://example.com/report.pdf"
        return {
            "symbol": "000333",
            "report": {
                "title": "2025年年度报告",
                "document_url": "https://example.com/report.pdf",
            },
            "report_text": "annual report text",
            "answers": [],
            "llm_analysis": None,
            "extracted_metrics": {"revenue": 100.0},
        }

    monkeypatch.setattr(report_qa_service.report_context_service, "artifact_row_to_context", fake_artifact_row_to_context)
    monkeypatch.setattr(
        report_qa_service,
        "fetch_report_artifact",
        lambda report_key: {
            "report_key": report_key,
            "symbol": "000333",
            "document_url": "https://example.com/report.pdf",
            "detail_url": None,
            "title": "2025年年度报告",
            "published_at": None,
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "report_text": "annual report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="收入怎么样？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    assert captured["mapper_calls"] == 1
    cached = report_qa_service.get_cached_report_context("000333|https://example.com/report.pdf")
    assert cached is not None
    assert cached["report"]["title"] == "2025年年度报告"


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
    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    assert payload["updated_session_summary"]
    assert "prior summary" in payload["updated_session_summary"]


def test_is_report_scoped_question_rejects_market_data_question() -> None:
    """Market-data questions should not be classified as report scoped."""
    context = {
        "report_text": "海外收入同比增长，经营现金流改善。",
        "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
    }

    assert report_qa_service._is_report_scoped_question(
        "公司股价现在多少？",
        context,
        [],
        "",
    ) is False


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
    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    assert payload["session_reset"] is False


def test_answer_report_question_accepts_llm_answer_alias_fields(monkeypatch) -> None:
    """Provider payloads that use answer/summary aliases should still render as hybrid answers."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        assert kwargs["question"] == "今年利润增长主要来自哪里？"
        return {
            "answer": "海外业务和产品结构优化带动利润改善。",
            "evidence": "海外收入同比增长",
            "citations": {"source": "report_text", "snippet": "海外收入同比增长"},
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "海外业务和产品结构优化带动利润改善。"
    assert payload["evidence"] == []
    assert payload["citations"] == [{"source": "report_text", "snippet": "海外收入同比增长"}]


def test_answer_report_question_cleans_dense_table_row_support_from_llm_payload(monkeypatch) -> None:
    """Dense table rows from the model should be compacted and de-duplicated before rendering."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": "贵州茅台2024年年度报告正文。",
            "answers": [],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "net_profit": 86228000000.0,
                "deducted_net_profit": 86240905977.42,
            },
        },
    )

    def fake_llm(**kwargs):
        assert kwargs["question"] == "扣非净利润和净利润分别为多少？"
        return {
            "short_answer": "扣非净利润为862.41亿元，净利润为862.28亿元。",
            "evidence": [
                "扣非净利润与净利润口径接近。",
                "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                "归属于上市公司股东的扣除非经常性损益的净利润 86,240,905,977.42 74,752,564,425.52 15.37 62,792,896,829.57",
            ],
            "citations": [
                {
                    "source": "report_text",
                    "snippet": "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                },
                {
                    "source": "report_text",
                    "snippet": "归属于上市公司股东的扣除非经常性损益的净利润 86,240,905,977.42 74,752,564,425.52 15.37 62,792,896,829.57",
                },
            ],
            "confidence": "high",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="扣非净利润和净利润分别为多少？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "扣非净利润为862.41亿元，净利润为862.28亿元。"
    assert payload["evidence"] == ["扣非净利润与净利润口径接近。"]
    assert payload["citations"] == [
        {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62。"},
        {"source": "report_text", "snippet": "归属于上市公司股东的扣除非经常性损益的净利润86,240,905,977.42。"},
    ]


def test_answer_report_question_answers_direct_numeric_metric_question_from_extracted_metrics() -> None:
    """Rule fallback should answer direct metric questions when structured values are already available."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": "贵州茅台2024年年度报告正文。",
            "answers": [],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="扣非净利润和净利润分别为多少？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert "扣非净利润约862.41亿元" in payload["short_answer"]
    assert "净利润约862.28亿元" in payload["short_answer"]
    assert payload["evidence"] == [
        "报告期（2024年）扣非净利润 = 86,240,905,977.42元（约862.41亿元）。",
        "报告期（2024年）净利润 = 86,228,146,421.62元（约862.28亿元）。",
    ]


def test_answer_report_question_answers_partially_when_one_direct_metric_is_missing() -> None:
    """Direct metric questions should surface available values and call out structured gaps explicitly."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": "贵州茅台2024年年度报告正文。",
            "answers": [
                {
                    "question": "这家企业净利润是否为真？",
                    "summary": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "net_profit": 86228146421.62,
                "deducted_net_profit": None,
            },
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="扣非净利润和净利润分别为多少？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert "净利润约862.28亿元" in payload["short_answer"]
    assert "扣非净利润原值当前未稳定抽取到" in payload["short_answer"]
    assert payload["evidence"] == [
        "报告期（2024年）扣非净利润补充线索：扣非净利润/净利润 = 1.00x。",
        "报告期（2024年）净利润 = 86,228,146,421.62元（约862.28亿元）。",
    ]


def test_answer_report_question_uses_report_reason_lines_for_growth_driver_fallback() -> None:
    """Growth-driver questions should prefer report reason lines over raw metric dumps."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": (
                "营业收入变动原因说明：主要是本期销量增加及茅台酒主要产品销售价格调整。 "
                "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"
            ),
            "answers": [
                {
                    "question": "净利润是否可持续？",
                    "summary": "收入、利润和资本回报率信号整体稳定，利润延续性较强。",
                    "evidence": ["收入 CAGR = 8.52%。", "最新收入同比 = 15.28%。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "revenue": 170899152276.34,
                "net_profit": 86228146421.62,
            },
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert "销量增加" in payload["short_answer"]
    assert "价格调整" in payload["short_answer"]
    assert payload["short_answer"] != "收入、利润和资本回报率信号整体稳定，利润延续性较强。"
    assert any("营业收入变动原因说明" in item for item in payload["evidence"])
    assert not any(item.startswith("revenue:") for item in payload["evidence"])


def test_answer_report_question_authenticity_follow_up_uses_fresh_explanatory_answer() -> None:
    """Authenticity follow-ups should not collapse back to the same generic cached summary after prior ratio answers."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": (
                "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"
            ),
            "answers": [
                {
                    "question": "这家企业净利润是否为真？",
                    "summary": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="为什么你认为净利润较为真实？",
        history=[
            {"role": "user", "content": "经营现金流和净利润匹配吗？"},
            {
                "role": "assistant",
                "content": "匹配，经营现金流/净利润 = 1.07x。",
                "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
            },
            {"role": "user", "content": "扣非净利润和净利润分别为多少？"},
            {
                "role": "assistant",
                "content": "扣非净利润约862.41亿元，净利润约862.28亿元。",
                "evidence": [
                    "报告期（2024年）扣非净利润 = 86,240,905,977.42元（约862.41亿元）。",
                    "报告期（2024年）净利润 = 86,228,146,421.62元（约862.28亿元）。",
                ],
            },
        ],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "利润与现金流、扣非口径的偏离不大，利润质量整体较好。"
    assert "经营现金流" in payload["short_answer"]
    assert "扣非净利润" in payload["short_answer"]
    assert payload["evidence"]


def test_answer_report_question_falls_back_when_llm_payload_has_no_answer_content(monkeypatch) -> None:
    """Empty LLM payloads should not be surfaced as hybrid answers with a blank body."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        return {
            "evidence": [],
            "citations": [],
            "confidence": "low",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "-"
    assert payload["session_reset"] is False


def test_answer_report_question_falls_back_when_numeric_llm_answer_has_no_citations(monkeypatch) -> None:
    """Numeric claims without citations should not be surfaced as hybrid report answers."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长43.12%，经营现金流改善。",
            "answers": [
                {
                    "question": "净利润是否可持续？",
                    "summary": "收入、利润和资本回报率信号整体稳定，利润延续性较强。",
                    "evidence": ["收入 CAGR = 8.52%。", "最新收入同比 = 43.12%。"],
                }
            ],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        return {
            "short_answer": "今年收入同比增长43.12%，主要来自海外业务。",
            "evidence": ["收入同比增长43.12%。"],
            "citations": [],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "rule_fallback"
    assert "43.12%" not in payload["short_answer"]
    assert payload["citations"] == []


def test_answer_report_question_logs_unusable_llm_payload(caplog, monkeypatch) -> None:
    """Unusable LLM payloads should be logged before the service falls back to rule-based answers."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        return {"confidence": "low"}

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    with caplog.at_level(logging.WARNING):
        payload = report_qa_service.answer_report_question(
            symbol="000333",
            report_key="000333|https://example.com/report.pdf",
            question="今年利润增长主要来自哪里？",
            history=[],
            session_summary="",
            use_llm=True,
        )

    assert payload["mode"] == "rule_fallback"
    assert (
        "report_qa unusable_llm_payload symbol=000333 report_key=000333|https://example.com/report.pdf "
        "question=今年利润增长主要来自哪里？"
    ) in caplog.text


def test_answer_report_question_returns_llm_hybrid_with_no_cached_answers_when_question_is_report_scoped(monkeypatch) -> None:
    """Report-scoped questions should still reach the LLM path even when there are no cached answers."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    def fake_llm(**kwargs):
        assert kwargs["question"] == "今年利润增长主要来自哪里？"
        assert kwargs["answers"] == []
        return {
            "short_answer": "growth drivers",
            "evidence": ["report evidence"],
            "citations": [{"source": "report_text", "snippet": "海外收入同比增长"}],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "growth drivers"
    assert payload["session_reset"] is False


def test_answer_report_question_returns_llm_hybrid_for_follow_up_wording_without_report_keywords(monkeypatch) -> None:
    """Follow-up wording alone should still reach the LLM when the session context anchors the report."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    captured: dict[str, object] = {}

    def fake_llm(**kwargs):
        captured["history"] = kwargs["history"]
        captured["session_summary"] = kwargs["session_summary"]
        captured["question"] = kwargs["question"]
        return {
            "short_answer": "follow-up answer",
            "evidence": ["report evidence"],
            "citations": [],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="能展开讲讲吗？",
        history=[
            {"role": "user", "content": "之前我们讨论过现金流"},
            {"role": "assistant", "content": "现金流确实改善。"},
        ],
        session_summary="上一轮重点在现金流改善。",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "follow-up answer"
    assert captured["history"] == [
        {"role": "user", "content": "之前我们讨论过现金流"},
        {"role": "assistant", "content": "现金流确实改善。"},
    ]
    assert captured["session_summary"] == "上一轮重点在现金流改善。"
    assert "上一轮关于“之前我们讨论过现金流”" in captured["question"]


def test_answer_report_question_returns_llm_hybrid_for_follow_up_without_cached_answer_match(monkeypatch) -> None:
    """Follow-up context should still allow LLM answering even without a cached-answer match."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    captured: dict[str, object] = {}

    def fake_llm(**kwargs):
        captured["history"] = kwargs["history"]
        captured["session_summary"] = kwargs["session_summary"]
        captured["question"] = kwargs["question"]
        return {
            "short_answer": "follow-up answer",
            "evidence": ["report evidence"],
            "citations": [],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="为什么会改善？",
        history=[
            {"role": "user", "content": "之前我们讨论过现金流"},
            {"role": "assistant", "content": "现金流确实改善。"},
        ],
        session_summary="上一轮重点在现金流改善。",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["short_answer"] == "follow-up answer"
    assert captured["history"] == [
        {"role": "user", "content": "之前我们讨论过现金流"},
        {"role": "assistant", "content": "现金流确实改善。"},
    ]
    assert captured["session_summary"] == "上一轮重点在现金流改善。"
    assert "上一轮关于“之前我们讨论过现金流”" in captured["question"]


def test_answer_report_question_forwards_structured_assistant_history_to_llm(monkeypatch) -> None:
    """Assistant history should preserve prior evidence and citations so the LLM can avoid repeats."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": "贵州茅台2024年年度报告正文。",
            "answers": [],
            "llm_analysis": None,
            "extracted_metrics": {},
        },
    )

    captured: dict[str, object] = {}

    def fake_llm(**kwargs):
        captured["history"] = kwargs["history"]
        return {
            "short_answer": "follow-up answer",
            "evidence": [],
            "citations": [{"source": "report_text", "snippet": "新增片段"}],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="为什么你认为净利润较为真实？",
        history=[
            {
                "role": "assistant",
                "content": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}],
            }
        ],
        session_summary="上一轮重点讲了现金流和扣非口径。",
        use_llm=True,
    )

    assert captured["history"] == [
        {
            "role": "assistant",
            "content": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
            "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
            "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}],
        }
    ]


def test_answer_report_question_filters_support_already_covered_by_recent_history(monkeypatch) -> None:
    """Repeated support from earlier assistant turns should be removed when the current answer adds nothing new."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF"},
            "report_text": "贵州茅台2024年年度报告正文。",
            "answers": [],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )

    def fake_llm(**kwargs):
        _ = kwargs
        return {
            "short_answer": "净利润较为真实，主要因为经营现金流与净利润匹配度高，且扣非净利润与净利润基本一致。",
            "evidence": [
                "经营现金流/净利润 = 1.07x。",
                "扣非净利润/净利润 = 1.00x。",
                "经营活动产生的现金流量净额92,463,692,168.43元。",
            ],
            "citations": [
                {"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"},
                {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62元。"},
                {"source": "report_text", "snippet": "归属于上市公司股东的扣除非经常性损益的净利润86,240,905,977.42元。"},
            ],
            "confidence": "high",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        question="为什么你认为净利润较为真实？",
        history=[
            {
                "role": "assistant",
                "content": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}],
            }
        ],
        session_summary="上一轮重点讲了现金流和扣非口径。",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert payload["evidence"] == []
    assert payload["citations"] == [
        {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62元。"},
        {"source": "report_text", "snippet": "归属于上市公司股东的扣除非经常性损益的净利润86,240,905,977.42元。"},
    ]


def test_answer_report_question_rewrites_weak_follow_up_to_last_non_generic_user_question(monkeypatch) -> None:
    """Weak wording like '也没有展开呀' should anchor to the last substantive user question."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善，管理层提示汇率与关税风险。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    captured: dict[str, object] = {}

    def fake_llm(**kwargs):
        captured["question"] = kwargs["question"]
        return {
            "short_answer": "expanded risk answer",
            "evidence": ["risk evidence"],
            "citations": [],
            "confidence": "medium",
        }

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="也没有展开呀",
        history=[
            {"role": "user", "content": "管理层最担心哪些风险？"},
            {"role": "assistant", "content": "主要是汇率、关税和行业竞争风险。"},
            {"role": "user", "content": "能展开讲讲吗？"},
            {"role": "assistant", "content": "我补充了几类风险。"},
        ],
        session_summary="上一轮主要讨论管理层风险。",
        use_llm=True,
    )

    assert payload["mode"] == "llm_hybrid"
    assert "上一轮关于“管理层最担心哪些风险？”" in captured["question"]


def test_answer_report_question_requests_clarification_for_unanchored_follow_up() -> None:
    """Generic follow-ups without a usable anchor should ask the user to name the topic to expand."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="能展开讲讲吗？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert "please specify which part" in payload["short_answer"].lower()
    assert payload["confidence"] == "low"


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
    assert payload["evidence"] == []
    assert payload["confidence"] == "low"
    assert payload["session_reset"] is False


def test_answer_report_question_rejects_out_of_scope_question_with_report_keywords(monkeypatch) -> None:
    """Out-of-scope questions should return a boundary fallback even when cached answers look related."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "000333|https://example.com/report.pdf",
        {
            "symbol": "000333",
            "report": {"title": "2025年年度报告", "document_url": "https://example.com/report.pdf"},
            "report_text": "海外收入同比增长，经营现金流改善。",
            "answers": [
                {
                    "question": "现金流怎么看？",
                    "summary": "现金流改善。",
                    "evidence": ["cashflow-answer-evidence"],
                }
            ],
            "llm_analysis": {"summary": "海外业务和 ToB 业务带动增长。"},
            "extracted_metrics": {"revenue": 100.0, "net_profit": 10.0},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="买入后现金流怎么看？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["mode"] == "rule_fallback"
    assert payload["short_answer"] != "现金流改善。"
    assert payload["evidence"] == []
    assert payload["confidence"] == "low"


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
    assert payload["evidence"] == []
    assert payload["confidence"] == "low"


def store_dialogue_context(report_key: str) -> None:
    """Store one shared report-QA dialogue context for regression-style multi-turn tests."""
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        report_key,
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": f"https://example.com/{report_key}.pdf"},
            "report_text": (
                "营业收入变动原因说明：主要是本期销量增加及茅台酒主要产品销售价格调整。 "
                "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"
            ),
            "answers": [
                {
                    "question": "这家企业净利润是否为真？",
                    "summary": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "revenue": 170899152276.34,
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )


def ask_and_append(
    history: list[dict[str, object]],
    question: str,
    *,
    session_summary: str,
    symbol: str,
    report_key: str,
    use_llm: bool,
) -> tuple[dict[str, Any], str]:
    """Call report-QA once, append the turn pair, and carry the returned session summary forward."""
    payload = report_qa_service.answer_report_question(
        symbol=symbol,
        report_key=report_key,
        question=question,
        history=cast(list[dict[str, Any]], history),
        session_summary=session_summary,
        use_llm=use_llm,
    )
    history.append({"role": "user", "content": question})
    history.append(
        {
            "role": "assistant",
            "content": str(payload["short_answer"]),
            "evidence": list(payload.get("evidence", [])),
            "citations": list(payload.get("citations", [])),
            "mode": payload.get("mode"),
        }
    )
    return payload, str(payload.get("updated_session_summary") or session_summary)


def test_report_qa_rule_only_dialogue_flow() -> None:
    """Dialogue regressions should protect the core rule-only report-QA flow across turns."""
    store_dialogue_context("600519|rule-dialogue")

    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(
        history,
        "扣非净利润和净利润分别为多少？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )
    q2, session_summary = ask_and_append(
        history,
        "为什么你认为净利润较为真实？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )
    q3, session_summary = ask_and_append(
        history,
        "今年利润增长主要来自哪里？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )

    assert q1["mode"] == "rule_fallback"
    assert "扣非净利润约862.41亿元" in q1["short_answer"]
    assert "净利润约862.28亿元" in q1["short_answer"]
    assert q2["mode"] == "rule_fallback"
    assert "经营现金流" in q2["short_answer"]
    assert "扣非净利润" in q2["short_answer"]
    assert q3["mode"] == "rule_fallback"
    assert "销量增加" in q3["short_answer"]
    assert "价格调整" in q3["short_answer"]


def test_report_qa_llm_hybrid_dialogue_flow(monkeypatch) -> None:
    """Dialogue regressions should protect hybrid LLM answers, cleaning, and fallback transitions."""
    store_dialogue_context("600519|hybrid-dialogue")

    responses = iter(
        [
            {
                "short_answer": "扣非净利润为862.41亿元，净利润为862.28亿元。",
                "evidence": [
                    "扣非净利润与净利润口径接近。",
                    "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                    "归属于上市公司股东的扣除非经常性损益的净利润 86,240,905,977.42 74,752,564,425.52 15.37 62,792,896,829.57",
                    "扣非净利润与净利润口径接近。",
                ],
                "citations": [
                    {
                        "source": "report_text",
                        "snippet": "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                    },
                    {
                        "source": "report_text",
                        "snippet": "归属于上市公司股东的扣除非经常性损益的净利润 86,240,905,977.42 74,752,564,425.52 15.37 62,792,896,829.57",
                    },
                    {
                        "source": "report_text",
                        "snippet": "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                    },
                ],
                "confidence": "high",
            },
            {
                "short_answer": "净利润较为真实，主要因为经营现金流与净利润匹配度高，且扣非净利润与净利润基本一致。",
                "evidence": [
                    "经营现金流/净利润 = 1.07x。",
                    "扣非净利润/净利润 = 1.00x。",
                ],
                "citations": [
                    {"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"},
                    {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62元。"},
                    {"source": "report_text", "snippet": "归属于上市公司股东的扣除非经常性损益的净利润86,240,905,977.42元。"},
                ],
                "confidence": "high",
            },
            {},
        ]
    )

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", lambda **_: next(responses))

    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(
        history,
        "扣非净利润和净利润分别为多少？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|hybrid-dialogue",
        use_llm=True,
    )
    q2, session_summary = ask_and_append(
        history,
        "为什么你认为净利润较为真实？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|hybrid-dialogue",
        use_llm=True,
    )
    q3, session_summary = ask_and_append(
        history,
        "今年利润增长主要来自哪里？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|hybrid-dialogue",
        use_llm=True,
    )

    assert q1["mode"] == "llm_hybrid"
    assert q1["evidence"] == ["扣非净利润与净利润口径接近。"]
    assert q1["citations"] == [
        {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62。"},
        {"source": "report_text", "snippet": "归属于上市公司股东的扣除非经常性损益的净利润86,240,905,977.42。"},
    ]
    assert q2["mode"] == "llm_hybrid"
    assert "经营现金流" in q2["short_answer"]
    assert "扣非净利润" in q2["short_answer"]
    assert q2["citations"] == [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}]
    assert q3["mode"] == "rule_fallback"
    assert "销量增加" in q3["short_answer"]


def test_report_qa_follow_up_dialogue_flow(monkeypatch) -> None:
    """Dialogue regressions should keep weak follow-ups anchored to the last substantive report turn."""
    store_dialogue_context("600519|follow-up-dialogue")

    captured_questions: list[str] = []
    responses = iter(
        [
            {
                "short_answer": "因为经营现金流高于净利润，且扣非净利润与净利润几乎一致，所以利润质量较好。",
                "evidence": ["经营现金流/净利润 = 1.07x。"],
                "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}],
                "confidence": "high",
            },
            {
                "short_answer": "更具体地说，销售收现增加让现金流兑现优于利润确认，扣非口径也没有明显失真。",
                "evidence": ["经营现金流较净利润高约6.24亿元。"],
                "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"}],
                "confidence": "medium",
            },
        ]
    )

    def fake_llm(**kwargs):
        captured_questions.append(str(kwargs["question"]))
        return next(responses)

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_llm)

    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(
        history,
        "经营现金流和净利润匹配吗？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|follow-up-dialogue",
        use_llm=False,
    )
    q2, session_summary = ask_and_append(
        history,
        "为什么这么说？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|follow-up-dialogue",
        use_llm=True,
    )
    q3, session_summary = ask_and_append(
        history,
        "也没有展开呀",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|follow-up-dialogue",
        use_llm=True,
    )

    clarification = report_qa_service.answer_report_question(
        symbol="600519",
        report_key="600519|follow-up-dialogue",
        question="展开一点",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert q1["mode"] == "rule_fallback"
    assert q2["mode"] == "llm_hybrid"
    assert "上一轮关于“经营现金流和净利润匹配吗？”" in captured_questions[0]
    assert q3["mode"] == "llm_hybrid"
    assert "上一轮关于“经营现金流和净利润匹配吗？”" in captured_questions[1]
    assert clarification["mode"] == "rule_fallback"
    assert "please specify which part" in clarification["short_answer"].lower()


def test_report_qa_scope_boundary_dialogue_flow(monkeypatch) -> None:
    """Dialogue regressions should route clear out-of-report turns away from report-scoped memory."""
    store_dialogue_context("600519|scope-dialogue")

    out_of_scope_responses = iter(
        [
            {"short_answer": "估值是否偏贵要结合当前价格、增长预期和市场风险偏好综合判断。", "confidence": "medium"},
            {"short_answer": "行业景气度需要看需求、价格和库存周期，不能只靠年报单点判断。", "confidence": "medium"},
        ]
    )
    report_follow_up_questions: list[str] = []

    def fake_general_llm(**kwargs):
        _ = kwargs
        return next(out_of_scope_responses)

    def fake_report_llm(**kwargs):
        report_follow_up_questions.append(str(kwargs["question"]))
        return {
            "short_answer": "之所以这样判断净利润，是因为经营现金流与净利润匹配度较高，且扣非口径与净利润基本一致。",
            "evidence": ["经营现金流/净利润 = 1.07x。"],
            "citations": [{"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"}],
            "confidence": "high",
        }

    monkeypatch.setattr(report_qa_service.llm_service, "answer_general_question", fake_general_llm)
    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", fake_report_llm)

    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(
        history,
        "净利润是否为真？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|scope-dialogue",
        use_llm=False,
    )
    q2, session_summary = ask_and_append(
        history,
        "那现在估值贵不贵？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|scope-dialogue",
        use_llm=True,
    )
    q3, session_summary = ask_and_append(
        history,
        "行业景气度怎么样？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|scope-dialogue",
        use_llm=True,
    )
    q4, session_summary = ask_and_append(
        history,
        "为什么这么说？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|scope-dialogue",
        use_llm=True,
    )

    assert q1["mode"] in {"rule_fallback", "llm_hybrid"}
    assert q2["mode"] == "out_of_report_llm"
    assert q3["mode"] == "out_of_report_llm"
    assert q2["updated_session_summary"] == q1["updated_session_summary"]
    assert q3["updated_session_summary"] == q1["updated_session_summary"]
    assert q4["mode"] == "llm_hybrid"
    assert "上一轮关于“净利润是否为真？”" in report_follow_up_questions[0]
