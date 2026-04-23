from __future__ import annotations

from fastapi import HTTPException

from app.api import financial_report_api


def test_financial_report_qa_rejects_invalid_symbol() -> None:
    """The Q&A endpoint should reject non-A-share symbols before orchestration."""
    payload = financial_report_api.FinancialReportQaRequest(
        symbol="bad",
        report_key="x",
        question="q",
        history=[],
        session_summary="",
        use_llm=True,
    )

    try:
        financial_report_api.financial_report_qa(payload)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover - defensive branch for the expected failure path
        raise AssertionError("expected HTTPException")


def test_financial_report_qa_forwards_normalized_symbol_and_plain_history(monkeypatch) -> None:
    """The route should normalize the symbol and pass plain dict history to the usecase."""
    captured: dict[str, object] = {}

    def fake_answer_financial_report_question(**kwargs):
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

    monkeypatch.setattr(financial_report_api, "answer_financial_report_question", fake_answer_financial_report_question)

    payload = financial_report_api.FinancialReportQaRequest(
        symbol=" 000333 ",
        report_key="000333|https://example.com/report.pdf",
        question=" 今年利润增长主要来自哪里？ ",
        history=[financial_report_api.FinancialReportQaTurn(role="user", content="旧问题")],
        session_summary="summary",
        use_llm=False,
    )

    response = financial_report_api.financial_report_qa(payload)

    assert response["report_key"] == "000333|https://example.com/report.pdf"
    assert captured["symbol"] == "000333"
    assert captured["report_key"] == "000333|https://example.com/report.pdf"
    assert captured["question"] == " 今年利润增长主要来自哪里？ "
    assert captured["history"] == [{"role": "user", "content": "旧问题"}]
    assert captured["session_summary"] == "summary"
    assert captured["use_llm"] is False


def test_financial_report_qa_maps_missing_report_context_to_422(monkeypatch) -> None:
    """Missing cached report context should surface as an unprocessable request."""
    def raise_missing_context(**_kwargs):
        raise ValueError("Active report context not found. Reload the report and try again.")

    monkeypatch.setattr(financial_report_api, "answer_financial_report_question", raise_missing_context)

    payload = financial_report_api.FinancialReportQaRequest(
        symbol="000333",
        report_key="000333|missing",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    try:
        financial_report_api.financial_report_qa(payload)
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == "Active report context not found. Reload the report and try again."
    else:  # pragma: no cover - defensive branch for the expected failure path
        raise AssertionError("expected HTTPException")


def test_financial_report_qa_maps_report_key_mismatch_to_422(monkeypatch) -> None:
    """Report-key mismatches should propagate through the route as validation failures."""
    def raise_mismatch(**_kwargs):
        raise ValueError("Report key does not match the requested symbol.")

    monkeypatch.setattr(financial_report_api, "answer_financial_report_question", raise_mismatch)

    payload = financial_report_api.FinancialReportQaRequest(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="今年利润增长主要来自哪里？",
        history=[],
        session_summary="",
        use_llm=True,
    )

    try:
        financial_report_api.financial_report_qa(payload)
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == "Report key does not match the requested symbol."
    else:  # pragma: no cover - defensive branch for the expected failure path
        raise AssertionError("expected HTTPException")


def test_analyze_route_forwards_refresh_flag(monkeypatch) -> None:
    """Single-stock route should pass the explicit refresh flag to the usecase."""
    captured: dict[str, object] = {}

    def fake_analyze_single_symbol(symbol: str, *, refresh: bool = False) -> dict:
        captured["symbol"] = symbol
        captured["refresh"] = refresh
        return {"symbol": symbol, "refresh": refresh}

    monkeypatch.setattr(financial_report_api, "normalize_stock_code", lambda raw: raw.strip())
    from app.api import market_api

    monkeypatch.setattr(market_api, "normalize_stock_code", lambda raw: raw.strip())
    monkeypatch.setattr(market_api, "analyze_single_symbol", fake_analyze_single_symbol)

    payload = market_api.AnalyzeRequest(stock_code=" 000333 ", refresh=True)
    response = market_api.analyze(payload)

    assert response["symbol"] == "000333"
    assert captured == {"symbol": "000333", "refresh": True}


def test_analyze_multi_route_keeps_refresh_default_false(monkeypatch) -> None:
    """Watchlist route should remain compatible when refresh is omitted."""
    captured: dict[str, object] = {}

    def fake_analyze_multi_symbols(stock_codes: list[str], *, refresh: bool = False) -> dict:
        captured["stock_codes"] = stock_codes
        captured["refresh"] = refresh
        return {"results": []}

    from app.api import market_api

    monkeypatch.setattr(market_api, "analyze_multi_symbols", fake_analyze_multi_symbols)

    payload = market_api.MultiAnalyzeRequest(stock_codes=["000333", "600900"])
    market_api.analyze_multi(payload)

    assert captured == {"stock_codes": ["000333", "600900"], "refresh": False}


def test_financial_report_analysis_forwards_refresh_query_flag(monkeypatch) -> None:
    """Financial-report route should pass the explicit refresh flag to the usecase."""
    captured: dict[str, object] = {}

    def fake_get_financial_report_analysis(symbol: str, *, refresh: bool = False) -> dict:
        captured["symbol"] = symbol
        captured["refresh"] = refresh
        return {"symbol": symbol, "refresh": refresh}

    monkeypatch.setattr(financial_report_api, "normalize_stock_code", lambda raw: raw.strip())
    monkeypatch.setattr(
        financial_report_api,
        "get_financial_report_analysis",
        fake_get_financial_report_analysis,
    )

    response = financial_report_api.financial_report_analysis(symbol=" 000333 ", refresh=True)

    assert response == {"symbol": "000333", "refresh": True}
    assert captured == {"symbol": "000333", "refresh": True}


def test_financial_report_autoread_forwards_force_refresh(monkeypatch) -> None:
    """Auto-read route should pass the explicit force_refresh flag to the usecase."""
    captured: dict[str, object] = {}

    def fake_autonomous_financial_report_read(symbol: str, *, force_refresh: bool = False) -> dict:
        captured["symbol"] = symbol
        captured["force_refresh"] = force_refresh
        return {"symbol": symbol, "force_refresh": force_refresh}

    monkeypatch.setattr(financial_report_api, "normalize_stock_code", lambda raw: raw.strip())
    monkeypatch.setattr(
        financial_report_api,
        "autonomous_financial_report_read",
        fake_autonomous_financial_report_read,
    )

    response = financial_report_api.financial_report_autoread(symbol=" 000333 ", force_refresh=True)

    assert response == {"symbol": "000333", "force_refresh": True}
    assert captured == {"symbol": "000333", "force_refresh": True}


def test_financial_report_url_analysis_forwards_force_refresh(monkeypatch) -> None:
    """Report URL route should pass the force_refresh flag through to the usecase."""
    captured: dict[str, object] = {}

    def fake_analyze_financial_report_url(url: str, symbol: str | None = None, *, force_refresh: bool = False) -> dict:
        captured["url"] = url
        captured["symbol"] = symbol
        captured["force_refresh"] = force_refresh
        return {"url": url, "symbol": symbol, "force_refresh": force_refresh}

    monkeypatch.setattr(financial_report_api, "normalize_stock_code", lambda raw: raw.strip())
    monkeypatch.setattr(
        financial_report_api,
        "analyze_financial_report_url",
        fake_analyze_financial_report_url,
    )

    payload = financial_report_api.FinancialReportUrlRequest(
        url="https://static.cninfo.com.cn/report.pdf",
        symbol=" 000333 ",
        force_refresh=True,
    )
    response = financial_report_api.financial_report_url_analysis(payload)

    assert response == {
        "url": "https://static.cninfo.com.cn/report.pdf",
        "symbol": "000333",
        "force_refresh": True,
    }
