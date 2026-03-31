from __future__ import annotations

from app.usecases import financial_report_usecase


def test_autonomous_financial_report_read_returns_partial_payload_on_report_failure(monkeypatch) -> None:
    """Usecase should keep a stable payload when report discovery/fetch partially fails."""
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
    assert payload["report"]["title"] == "2024年年度报告"
    assert len(payload["answers"]) == 3
    assert all("question" in item for item in payload["answers"])
    assert payload["warnings"] == []


def test_autonomous_financial_report_read_returns_insufficient_answers_when_sources_fail(monkeypatch) -> None:
    """Usecase should degrade to explicit insufficient-data answers instead of crashing."""
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
        "interpret_annual_report_text",
        lambda **_kwargs: {
            "summary": "LLM summary",
            "question_notes": [
                {
                    "question_id": "profit_authenticity",
                    "summary": "LLM judged cash conversion as healthy.",
                    "evidence": ["经营现金流覆盖净利润。"],
                }
            ],
        },
    )

    payload = financial_report_usecase.autonomous_financial_report_read("000333")

    assert payload["current_mode"] == "report_text_extracted"
    assert payload["llm_used"] is True
    assert payload["llm_provider"] == "deepseek"
    assert payload["llm_model"] == "deepseek-chat"
    assert payload["llm_analysis"]["summary"] == "LLM summary"


def test_autonomous_financial_report_read_falls_back_when_llm_interpretation_fails(monkeypatch) -> None:
    """Usecase should keep rule-based output when the configured LLM call fails."""
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
