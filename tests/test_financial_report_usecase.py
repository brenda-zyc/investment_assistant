from __future__ import annotations

import app.services.report_qa_service as report_qa_service
from app.usecases import financial_report_usecase


def test_autonomous_financial_report_read_returns_partial_payload_on_report_failure(monkeypatch) -> None:
    """Usecase should keep a stable payload when report discovery/fetch partially fails."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_stock_names",
        lambda symbols: {symbols[0]: "美的集团"},
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2024年年度报告",
            "published_at": "2025-03-20 18:00:00",
            "detail_url": "http://example.com/detail",
            "document_url": "http://example.com/report.pdf",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "2024年年度报告。营业收入100亿元，归属于上市公司股东的净利润10亿元，"
            "归属于上市公司股东的扣除非经常性损益的净利润9亿元，"
            "经营活动产生的现金流量净额12亿元，购建固定资产、无形资产和其他长期资产支付的现金3亿元，"
            "净资产收益率16.0%，资产负债率45.0%。报告期：2024年12月31日。",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "2024年年度报告",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_assessment_context",
        lambda _symbol: {
            "revenue": [("2022-12-31", 80.0), ("2023-12-31", 90.0), ("2024-12-31", 100.0)],
            "net_profit": [("2022-12-31", 7.0), ("2023-12-31", 8.0), ("2024-12-31", 10.0)],
            "roe": [("2024-12-31", 16.0)],
            "debt_ratio": [("2024-12-31", 45.0)],
            "deducted_net_profit": [("2024-12-31", 9.0)],
            "operating_cash_flow": [("2024-12-31", 12.0)],
            "capex_cash_outflow": [("2024-12-31", 3.0)],
        },
    )

    payload = financial_report_usecase.autonomous_financial_report_read("000333")

    assert payload["symbol"] == "000333"
    assert payload["symbol_name"] == "美的集团"
    assert payload["analysis_mode"] == "rule_based"
    assert payload["llm_enabled"] is False
    assert payload["current_mode"] == "report_text_extracted"
    assert payload["llm_used"] is False
    assert payload["report_key"] == "000333|http://example.com/report.pdf"
    assert payload["report"]["title"] == "2024年年度报告"
    assert len(payload["answers"]) == 3
    assert all("question" in item for item in payload["answers"])
    assert payload["warnings"] == []
    cached_context = report_qa_service.get_cached_report_context(payload["report_key"])
    assert cached_context is not None
    assert cached_context["symbol"] == "000333"
    assert cached_context["report"]["document_url"] == "http://example.com/report.pdf"


def test_autonomous_financial_report_read_returns_insufficient_answers_when_sources_fail(monkeypatch) -> None:
    """Usecase should degrade to explicit insufficient-data answers instead of crashing."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {})

    def raise_discovery(_symbol: str) -> dict:
        raise RuntimeError("discovery down")

    def raise_context(_symbol: str) -> dict:
        raise RuntimeError("context down")

    monkeypatch.setattr(financial_report_usecase, "find_latest_annual_report", raise_discovery)
    monkeypatch.setattr(financial_report_usecase, "fetch_report_assessment_context", raise_context)

    payload = financial_report_usecase.autonomous_financial_report_read("000333")

    assert payload["report"]["title"] is None
    assert payload["current_mode"] == "historical_fallback"
    assert payload["llm_used"] is False
    assert len(payload["answers"]) == 3
    assert all(item["verdict"] == "数据不足" for item in payload["answers"])
    assert any("Annual report discovery failed." in item for item in payload["warnings"])
    assert any("Historical report context fetch failed." in item for item in payload["warnings"])


def test_autonomous_financial_report_read_uses_llm_when_report_text_and_session_config_exist(monkeypatch) -> None:
    """Usecase should attach LLM interpretation when report text exists and a session config is available."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_stock_names",
        lambda symbols: {symbols[0]: "美的集团"},
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2024年年度报告",
            "published_at": "2025-03-20 18:00:00",
            "detail_url": "http://example.com/detail",
            "document_url": "http://example.com/report.pdf",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "2024年年度报告。营业收入100亿元，归属于上市公司股东的净利润10亿元。",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "2024年年度报告",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_assessment_context",
        lambda _symbol: {
            "revenue": [("2023-12-31", 90.0), ("2024-12-31", 100.0)],
            "net_profit": [("2023-12-31", 8.0), ("2024-12-31", 10.0)],
            "roe": [("2024-12-31", 16.0)],
            "debt_ratio": [("2024-12-31", 45.0)],
            "deducted_net_profit": [],
            "operating_cash_flow": [],
            "capex_cash_outflow": [],
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "get_effective_llm_config",
        lambda: {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "build_autoread_llm_excerpt",
        lambda text, title=None, max_chars=6000: f"compressed::{title}::{text[:20]}",
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "interpret_annual_report_text",
        lambda **kwargs: {
            "summary": "LLM summary",
            "question_notes": [
                {
                    "question_id": "profit_authenticity",
                    "summary": "LLM judged cash conversion as healthy.",
                    "evidence": ["经营现金流覆盖净利润。"],
                }
            ],
            "debug_excerpt": kwargs["report_text"],
        },
    )

    payload = financial_report_usecase.autonomous_financial_report_read("000333")

    assert payload["current_mode"] == "report_text_extracted"
    assert payload["llm_used"] is True
    assert payload["llm_provider"] == "deepseek"
    assert payload["llm_model"] == "deepseek-chat"
    assert payload["llm_analysis"]["summary"] == "LLM summary"
    assert payload["llm_analysis"]["debug_excerpt"].startswith("compressed::2024年年度报告::")


def test_autonomous_financial_report_read_falls_back_when_llm_interpretation_fails(monkeypatch) -> None:
    """Usecase should keep rule-based output when the configured LLM call fails."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda symbols: {symbols[0]: "美的集团"})
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2024年年度报告",
            "published_at": "2025-03-20 18:00:00",
            "detail_url": "http://example.com/detail",
            "document_url": "http://example.com/report.pdf",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "2024年年度报告。营业收入100亿元，归属于上市公司股东的净利润10亿元。",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "2024年年度报告",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_assessment_context",
        lambda _symbol: {
            "revenue": [("2023-12-31", 90.0), ("2024-12-31", 100.0)],
            "net_profit": [("2023-12-31", 8.0), ("2024-12-31", 10.0)],
            "roe": [("2024-12-31", 16.0)],
            "debt_ratio": [("2024-12-31", 45.0)],
            "deducted_net_profit": [],
            "operating_cash_flow": [],
            "capex_cash_outflow": [],
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "get_effective_llm_config",
        lambda: {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        },
    )

    def raise_llm(**_kwargs) -> dict:
        raise RuntimeError("llm timeout")

    monkeypatch.setattr(financial_report_usecase, "interpret_annual_report_text", raise_llm)

    payload = financial_report_usecase.autonomous_financial_report_read("000333")

    assert payload["current_mode"] == "report_text_extracted"
    assert payload["llm_enabled"] is True
    assert payload["llm_used"] is False
    assert payload["llm_analysis"] is None
    assert any("LLM interpretation failed." in item for item in payload["warnings"])


def test_autonomous_financial_report_read_prefers_report_meta_title_for_pdf_extraction(monkeypatch) -> None:
    """Usecase should pass the disclosure title, not the PDF filename, into text extraction heuristics."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda symbols: {symbols[0]: "美的集团"})
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2025年年度报告",
            "published_at": "2026-03-31 00:00:00",
            "detail_url": "http://example.com/detail",
            "document_url": "http://example.com/1225065145.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "dummy report text",
            "content_type": "application/pdf",
            "pdf_pages": 276,
            "tls_insecure": False,
            "title": "1225065145.PDF",
        },
    )
    monkeypatch.setattr(financial_report_usecase, "fetch_report_assessment_context", lambda _symbol: {})

    captured: dict[str, str | None] = {}

    def fake_extract(_text: str, title: str | None = None) -> dict:
        captured["title"] = title
        return {
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 458500000000.0,
            "net_profit": 43950000000.0,
            "roe": 19.7,
            "debt_ratio": 60.54,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        }

    monkeypatch.setattr(financial_report_usecase, "extract_report_assessment_metrics", fake_extract)

    financial_report_usecase.autonomous_financial_report_read("000333")

    assert captured["title"] == "2025年年度报告"


def test_analyze_financial_report_url_returns_report_key_and_caches_context(monkeypatch) -> None:
    """URL analysis should expose a report key and store the active report context for follow-up Q&A."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_report_artifact", lambda _report_key: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda url: {
            "url": url,
            "text": "2024年年度报告。营业收入100亿元，归属于上市公司股东的净利润10亿元。",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "2024年年度报告",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": 100000000000.0,
            "net_profit": 10000000000.0,
            "roe": 16.0,
            "debt_ratio": 45.0,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )

    payload = financial_report_usecase.analyze_financial_report_url(
        "https://example.com/report.pdf",
        symbol="000333",
    )

    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    cached_context = report_qa_service.get_cached_report_context(payload["report_key"])
    assert cached_context is not None
    assert cached_context["symbol"] == "000333"
    assert cached_context["report"]["document_url"] == "https://example.com/report.pdf"
    assert cached_context["report_text"].startswith("2024年年度报告")


def test_analyze_financial_report_url_returns_none_report_key_when_report_text_is_empty(monkeypatch) -> None:
    """URL analysis should not advertise a report key when no active context was cached."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_report_artifact", lambda _report_key: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda url: {
            "url": url,
            "text": "",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "2024年年度报告",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": None,
            "net_profit": None,
            "roe": None,
            "debt_ratio": None,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )

    payload = financial_report_usecase.analyze_financial_report_url(
        "https://example.com/report.pdf",
        symbol="000333",
    )

    assert payload["report_key"] is None
    assert report_qa_service.get_cached_report_context("000333|https://example.com/report.pdf") is None


def test_analyze_financial_report_url_keeps_unknown_report_year_as_missing(monkeypatch) -> None:
    """URL analysis should not fabricate the current year when report-year evidence is missing."""
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda url: {
            "url": url,
            "text": "公告页仅提到营业收入100亿元和净利润10亿元，但没有明确年度。",
            "content_type": "text/html",
            "pdf_pages": None,
            "tls_insecure": False,
            "title": "某公告页面",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "report_year": None,
            "report_date": None,
            "revenue": 100000000000.0,
            "net_profit": 10000000000.0,
            "roe": None,
            "debt_ratio": None,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )

    payload = financial_report_usecase.analyze_financial_report_url("https://example.com/report.html")

    assert payload["analysis"]["latest_report_year"] is None
    assert payload["analysis"]["score"] is None
    assert payload["analysis"]["grade"] is None
    assert any(item["title"] == "No financial data" for item in payload["analysis"]["highlights"])
    assert payload["extracted"]["report_year"] is None


def test_answer_financial_report_question_strips_question_and_delegates(monkeypatch) -> None:
    """The usecase wrapper should validate input and delegate a normalized payload to the service."""
    captured: dict[str, object] = {}

    def fake_answer_report_question(**kwargs):
        captured.update(kwargs)
        return {
            "report_key": kwargs["report_key"],
            "mode": "rule_fallback",
            "short_answer": "ok",
            "evidence": [],
            "citations": [],
            "confidence": "low",
            "updated_session_summary": kwargs["session_summary"],
            "session_reset": False,
        }

    monkeypatch.setattr(financial_report_usecase, "answer_report_question_service", fake_answer_report_question)

    payload = financial_report_usecase.answer_financial_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question=" 今年利润增长主要来自哪里？ ",
        history=[{"role": "user", "content": "旧问题"}],
        session_summary="summary",
        use_llm=True,
    )

    assert payload["report_key"] == "000333|https://example.com/report.pdf"
    assert captured["question"] == "今年利润增长主要来自哪里？"
    assert captured["history"] == [{"role": "user", "content": "旧问题"}]
    assert captured["use_llm"] is True


def test_get_financial_report_analysis_uses_cache_without_upstream_when_refresh_false(monkeypatch) -> None:
    """Report-summary analysis should reuse cached rows unless refresh is explicitly requested."""
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_financial_reports",
        lambda symbol: [
            {
                "symbol": symbol,
                "report_year": 2025,
                "report_date": "2025-12-31",
                "revenue": 1.0,
                "net_profit": 0.2,
                "roe": 12.0,
                "debt_ratio": 40.0,
            }
        ],
    )

    def fail_fetch(_symbol: str):
        raise AssertionError("financial upstream fetch should not run")

    monkeypatch.setattr(financial_report_usecase, "fetch_financial_summary", fail_fetch)
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {})

    payload = financial_report_usecase.get_financial_report_analysis("000333", refresh=False)

    assert payload["symbol"] == "000333"
    assert payload["series"]
    assert payload["warnings"] == []


def test_financial_report_autoread_reuses_latest_artifact_when_force_refresh_false(monkeypatch) -> None:
    """Auto-read should reuse the latest persisted artifact unless force refresh is requested."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_latest_report_artifact_for_symbol",
        lambda symbol: {
            "report_key": "000333|https://static.cninfo.com.cn/report.pdf",
            "symbol": symbol,
            "document_url": "https://static.cninfo.com.cn/report.pdf",
            "detail_url": "https://www.cninfo.com.cn/detail",
            "title": "2025年年度报告",
            "published_at": "2026-03-28 20:00:00",
            "content_type": "application/pdf",
            "pdf_pages": 180,
            "report_text": "cached report text",
            "extracted_metrics": {
                "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
                "report_date": "2025-12-31",
                "revenue": 100.0,
            },
            "answers": [{"id": "profit_authenticity", "summary": "cached"}],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {})
    monkeypatch.setattr(financial_report_usecase, "fetch_report_assessment_context", lambda _symbol: {})
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)

    def fail_discovery(_symbol: str):
        raise AssertionError("report discovery should not run")

    monkeypatch.setattr(financial_report_usecase, "find_latest_annual_report", fail_discovery)

    payload = financial_report_usecase.autonomous_financial_report_read("000333", force_refresh=False)

    assert payload["report_key"] == "000333|https://static.cninfo.com.cn/report.pdf"
    assert payload["answers"][0]["summary"] == "cached"
    cached_context = report_qa_service.get_cached_report_context(payload["report_key"])
    assert cached_context is not None
    assert cached_context["report_text"] == "cached report text"


def test_financial_report_autoread_ignores_current_url_analysis_artifact_for_same_symbol(monkeypatch) -> None:
    """Auto-read should not reuse a same-symbol artifact created by manual URL analysis."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_latest_report_artifact_for_symbol",
        lambda symbol: {
            "report_key": "600519|https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
            "symbol": symbol,
            "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
            "detail_url": None,
            "title": "1225002214.PDF",
            "published_at": None,
            "content_type": "application/pdf",
            "pdf_pages": 232,
            "report_text": "manual url analysis report text",
            "extracted_metrics": {
                "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
                "report_year": 2025,
                "report_date": "2025-12-31",
                "revenue": 423_701_834_000.0,
                "net_profit": 72_201_282_000.0,
            },
            "answers": [{"id": "profit_authenticity", "summary": "manual"}],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-12T09:00:00",
        },
    )
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {"600519": "贵州茅台"})
    monkeypatch.setattr(financial_report_usecase, "fetch_report_assessment_context", lambda _symbol: {})
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2025年年度报告",
            "published_at": "2026-03-31 00:00:00",
            "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?plate=sh&stockCode=600519",
            "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225999999.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "fresh moutai report text",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "tls_insecure": False,
            "title": "1225999999.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 174_100_000_000.0,
            "net_profit": 87_000_000_000.0,
            "roe": None,
            "debt_ratio": None,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)

    payload = financial_report_usecase.autonomous_financial_report_read("600519", force_refresh=False)

    assert payload["symbol"] == "600519"
    assert payload["report"]["title"] == "2025年年度报告"
    assert payload["report_key"] == "600519|https://static.cninfo.com.cn/finalpage/2026-03-31/1225999999.PDF"
    assert payload["answers"][0]["summary"] != "manual"


def test_analyze_financial_report_url_reuses_matching_artifact_when_force_refresh_false(monkeypatch) -> None:
    """URL analysis should return a persisted artifact when the report key already exists."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_artifact",
        lambda report_key: {
            "report_key": report_key,
            "symbol": "000333",
            "document_url": "https://static.cninfo.com.cn/report.pdf",
            "detail_url": None,
            "title": "2025年年度报告",
            "published_at": None,
            "content_type": "application/pdf",
            "pdf_pages": 180,
            "report_text": "cached report text",
            "extracted_metrics": {
                "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
                "report_year": 2025,
                "report_date": "2025-12-31",
                "revenue": 100.0,
                "net_profit": 10.0,
                "roe": 16.0,
                "debt_ratio": 45.0,
            },
            "answers": [],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )

    def fail_fetch(_url: str):
        raise AssertionError("report fetch should not run")

    monkeypatch.setattr(financial_report_usecase, "fetch_report_text_from_url", fail_fetch)

    payload = financial_report_usecase.analyze_financial_report_url(
        "https://static.cninfo.com.cn/report.pdf",
        symbol="000333",
        force_refresh=False,
    )

    assert payload["report_key"] == "000333|https://static.cninfo.com.cn/report.pdf"
    assert payload["extracted"]["revenue"] == 100.0


def test_analyze_financial_report_url_refreshes_stale_artifact_without_current_extraction_version(monkeypatch) -> None:
    """URL analysis should ignore stale cached artifacts created before the current parser rules."""
    report_qa_service.clear_report_context_cache()
    captured: dict[str, object] = {"fetches": 0, "persisted": None}

    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_artifact",
        lambda report_key: {
            "report_key": report_key,
            "symbol": "300750",
            "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
            "detail_url": None,
            "title": "1225002214.PDF",
            "published_at": None,
            "content_type": "application/pdf",
            "pdf_pages": 232,
            "report_text": "stale report text",
            "extracted_metrics": {
                "report_year": 2050,
                "report_date": "2026-03-09",
                "revenue": 423_701_834.0,
                "net_profit": 0.0,
                "roe": None,
                "debt_ratio": 61.94,
            },
            "answers": [],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )

    def fake_fetch(url: str) -> dict:
        captured["fetches"] = int(captured["fetches"]) + 1
        return {
            "url": url,
            "text": "fresh report text",
            "content_type": "application/pdf",
            "pdf_pages": 232,
            "tls_insecure": False,
            "title": "1225002214.PDF",
        }

    monkeypatch.setattr(financial_report_usecase, "fetch_report_text_from_url", fake_fetch)
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 423_701_834_000.0,
            "net_profit": 72_201_282_000.0,
            "roe": None,
            "debt_ratio": 61.94,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "upsert_report_artifact",
        lambda row: captured.__setitem__("persisted", row),
    )

    payload = financial_report_usecase.analyze_financial_report_url(
        "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
        symbol="300750",
        force_refresh=False,
    )

    assert captured["fetches"] == 1
    assert payload["analysis"]["latest_report_year"] == 2025
    assert payload["analysis"]["as_of"] == "2025-12-31"
    assert payload["extracted"]["net_profit"] == 72_201_282_000.0
    assert captured["persisted"]["extracted_metrics"]["extraction_version"] == financial_report_usecase.REPORT_EXTRACTION_VERSION


def test_financial_report_autoread_refreshes_stale_artifact_without_current_extraction_version(monkeypatch) -> None:
    """Auto-read should refresh stale cached artifacts instead of reusing older parser output forever."""
    report_qa_service.clear_report_context_cache()
    captured: dict[str, object] = {"persisted": None}
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_latest_report_artifact_for_symbol",
        lambda symbol: {
            "report_key": "300750|https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
            "symbol": symbol,
            "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
            "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?plate=szse&orgId=9900000000&stockCode=300750",
            "title": "1225002214.PDF",
            "published_at": "2026-03-10 00:00:00",
            "content_type": "application/pdf",
            "pdf_pages": 232,
            "report_text": "stale report text",
            "extracted_metrics": {
                "report_year": 2050,
                "report_date": "2026-03-09",
                "revenue": 423_701_834.0,
                "net_profit": 0.0,
            },
            "answers": [{"id": "profit_authenticity", "summary": "stale"}],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {"300750": "宁德时代"})
    monkeypatch.setattr(financial_report_usecase, "fetch_report_assessment_context", lambda _symbol: {})
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "2025年年度报告",
            "published_at": "2026-03-10 00:00:00",
            "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?plate=szse&orgId=9900000000&stockCode=300750",
            "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "fresh report text",
            "content_type": "application/pdf",
            "pdf_pages": 232,
            "tls_insecure": False,
            "title": "1225002214.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 423_701_834_000.0,
            "net_profit": 72_201_282_000.0,
            "roe": None,
            "debt_ratio": 61.94,
            "deducted_net_profit": None,
            "operating_cash_flow": None,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "upsert_report_artifact",
        lambda row: captured.__setitem__("persisted", row),
    )

    payload = financial_report_usecase.autonomous_financial_report_read("300750", force_refresh=False)

    assert payload["report"]["title"] == "2025年年度报告"
    assert payload["as_of"] == "2025-12-31"
    assert payload["extracted_metrics"]["report_year"] == 2025
    assert payload["answers"][0]["summary"] != "stale"
    assert captured["persisted"]["extracted_metrics"]["extraction_version"] == financial_report_usecase.REPORT_EXTRACTION_VERSION


def test_financial_report_autoread_uses_active_report_date_for_as_of_when_history_has_newer_date(monkeypatch) -> None:
    """Auto-read should label the active annual report date, not a newer historical series endpoint."""
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(financial_report_usecase, "fetch_latest_report_artifact_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(financial_report_usecase, "upsert_report_artifact", lambda _row: None)
    monkeypatch.setattr(financial_report_usecase, "get_effective_llm_config", lambda: None)
    monkeypatch.setattr(financial_report_usecase, "fetch_stock_names", lambda _symbols: {"600519": "贵州茅台"})
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_assessment_context",
        lambda _symbol: {
            "revenue": [("2025-12-31", 180.0)],
            "net_profit": [("2025-12-31", 90.0)],
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "find_latest_annual_report",
        lambda symbol: {
            "symbol": symbol,
            "title": "贵州茅台2024年年度报告",
            "published_at": "2025-04-03 00:00:00",
            "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519",
            "document_url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_report_text_from_url",
        lambda _url: {
            "text": "fresh report text",
            "content_type": "application/pdf",
            "pdf_pages": 143,
            "tls_insecure": False,
            "title": "1222993920.PDF",
        },
    )
    monkeypatch.setattr(
        financial_report_usecase,
        "extract_report_assessment_metrics",
        lambda _text, title=None: {
            "extraction_version": financial_report_usecase.REPORT_EXTRACTION_VERSION,
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": 170_899_152_276.34,
            "net_profit": 86_228_000_000.0,
            "roe": None,
            "debt_ratio": None,
            "deducted_net_profit": 86_240_905_977.42,
            "operating_cash_flow": 92_463_692_168.43,
            "capex_cash_outflow": None,
            "evidence": [],
            "warnings": [],
        },
    )

    payload = financial_report_usecase.autonomous_financial_report_read("600519", force_refresh=False)

    assert payload["report"]["title"] == "贵州茅台2024年年度报告"
    assert payload["as_of"] == "2024-12-31"
