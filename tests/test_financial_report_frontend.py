from __future__ import annotations

import re
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "index.html"


def _function_body(source: str, function_signature: str) -> str:
    """Return the body text for a named JavaScript function in the HTML template."""
    start = source.index(function_signature)
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : index]
    raise AssertionError(f"Could not locate function body for {function_signature!r}")


def test_auto_read_annual_report_resets_stale_financial_report_sections() -> None:
    """Auto-read should clear previously rendered summary sections before fetching a new symbol."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport()")

    reset_call = "resetFinancialReportPanel();"
    assert reset_call in body

    reset_index = body.index(reset_call)
    fetch_index = body.index("const res = await fetch(")
    assert reset_index < fetch_index


def test_auto_read_annual_report_has_empty_state_for_missing_report_source() -> None:
    """Auto-read should explain when no annual-report source metadata is available."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport()")

    assert re.search(r"Report source metadata unavailable", body)


def test_financial_report_template_includes_llm_settings_panel_hooks() -> None:
    """Financial Reports UI should expose LLM settings controls and mode/status placeholders."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="llmApiKeyInput"' in source
    assert 'id="llmBaseUrlInput"' in source
    assert 'id="llmModelInput"' in source
    assert 'id="saveLlmSessionBtn"' in source
    assert 'id="testLlmConnectionBtn"' in source
    assert 'id="reportCurrentMode"' in source
    assert 'id="reportLlmStatus"' in source
    assert 'id="reportLlmAnalysis"' in source
    assert "localStorage" in source


def test_financial_report_template_includes_report_qa_panel() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="reportQaSection"' in source
    assert 'id="reportQaSessionLabel"' in source
    assert 'id="reportQaChipList"' in source
    assert 'id="reportQaTranscript"' in source
    assert 'id="reportQaInput"' in source
    assert 'id="reportQaAskBtn"' in source


def test_financial_report_template_includes_guided_question_chips() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "今年利润增长主要来自哪里？" in source
    assert "经营现金流和净利润匹配吗？" in source
    assert "资本开支压力大吗？" in source


def test_financial_report_template_includes_report_qa_session_hooks() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "let reportQaSession" in source
    assert "resetReportQaSession" in source
    assert "reportQaSession = {" in source
    assert "Started a new Q&A session for the active report." in source
    assert "report_key" in source


def test_financial_report_template_includes_report_qa_ask_flow() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function askActiveReport()")

    assert 'fetch(`${apiBase}/api/financial-report-qa`' in body
    assert 'appendReportQaTurn("user", question);' in body
    assert "history: reportQaSession.history.map" in body
    assert "reportQaSession.sessionSummary" in body
    assert "updated_session_summary" in body
    assert "renderReportQaTranscript" in body


def test_financial_report_template_rolls_back_user_turn_when_qa_request_fails() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function askActiveReport()")

    assert "const previousHistorySnapshot = reportQaSession.history.map((turn) => ({ ...turn }));" in body
    assert "reportQaSession.history = previousHistorySnapshot;" in body


def test_financial_report_template_ignores_enter_during_ime_composition() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'if (e.key === "Enter" && !e.isComposing) askActiveReport();' in source


def test_financial_report_url_analysis_sends_symbol_with_report_url() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadFinancialReportFromUrl()")

    assert 'const reportSymbol = /^\\d{6}$/.test(reportCodeInput.value.trim()) ? reportCodeInput.value.trim() : null;' in body
    assert "body: JSON.stringify(reportSymbol ? { url, symbol: reportSymbol } : { url })" in body


def test_financial_report_url_analysis_resets_report_qa_before_fetch() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadFinancialReportFromUrl()")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)


def test_auto_read_resets_report_qa_before_fetch() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport()")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)
