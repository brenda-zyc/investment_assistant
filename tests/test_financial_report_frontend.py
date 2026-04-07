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
    assert 'id="reportQaOlderToggle"' in source
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
    assert "let reportQaShowOlderTurns = false;" in source
    assert "resetReportQaSession" in source
    assert "reportQaSession = {" in source
    assert "Started a new Q&A session for the active report." in source
    assert "report_key" in source


def test_financial_report_template_includes_report_qa_ask_flow() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function askActiveReport()")

    assert 'fetch(`${apiBase}/api/financial-report-qa`' in body
    assert 'appendReportQaTurn("user", question);' in body
    assert "history: reportQaSession.history.slice(-6).map" in body
    assert "reportQaSession.sessionSummary" in body
    assert "updated_session_summary" in body
    assert "renderReportQaTranscript" in body


def test_financial_report_template_keeps_full_transcript_and_renders_older_toggle() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    append_body = _function_body(source, "function appendReportQaTurn(role, content, payload = {})")
    render_body = _function_body(source, "function renderReportQaTranscript()")

    assert "reportQaSession.history = reportQaSession.history.slice(-6);" not in append_body
    assert "function countReportQaPairs(turns)" in source
    assert "const olderTurns = reportQaSession.history.slice(0, -6);" in render_body
    assert "const olderPairCount = countReportQaPairs(olderTurns);" in render_body
    assert "const visibleTurns = reportQaShowOlderTurns ? reportQaSession.history : reportQaSession.history.slice(-6);" in render_body
    assert 'reportQaOlderToggleEl.hidden = olderTurns.length === 0;' in render_body
    assert '`Hide older Q&A pairs (${olderPairCount})`' in render_body
    assert '`Show older Q&A pairs (${olderPairCount})`' in render_body


def test_financial_report_template_formats_report_qa_bold_text_safely() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "function formatReportQaRichText(value)" in source
    assert ".replace(/\\*\\*(.+?)\\*\\*/g, \"<strong>$1</strong>\")" in source
    assert 'bodyEl.innerHTML = formatReportQaRichText(turn.content || "-");' in source


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


def test_dashboard_template_includes_external_data_reference_section() -> None:
    """Dashboard UI should expose the external-data table and render rows from industry payloads."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="externalDataTable"' in source
    assert 'id="externalDataStatus"' in source
    assert 'id="refreshExternalDataBtn"' in source
    assert "External Data References" in source
    assert "cached weekly snapshots" in source
    assert "function renderExternalDataReferences(rows)" in source
    assert "async function loadCachedIndustryCycles()" in source
    assert "async function refreshExternalDataReferences()" in source
    assert "data.external_rows || []" in source
    assert "/industry_cycles?refresh=true&refresh_external=false" in source
    assert "/industry_cycles?refresh=false&refresh_external=false" in source
    assert "/industry_cycles?refresh=false&refresh_external=true" in source


def test_load_industry_cycles_does_not_touch_external_reference_table() -> None:
    """Industry refresh should not clear or rerender the external reference table."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadIndustryCycles()")

    assert 'loadIndustryBtn.disabled = true;' in body
    assert 'refreshExternalDataBtn.disabled = true;' not in body
    assert 'refreshExternalDataBtn.disabled = false;' not in body
    assert "renderIndustryRows(rows);" in body
    assert "renderExternalDataReferences(data.external_rows || []);" not in body
    assert "externalDataTableBody.innerHTML = \"\";" not in body


def test_load_cached_industry_cycles_reads_cache_and_renders_both_tables() -> None:
    """Initial industry-tab load should read cached data and render both tables."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadCachedIndustryCycles()")

    assert "/industry_cycles?refresh=false&refresh_external=false" in body
    assert "renderIndustryRows(rows);" in body
    assert "renderExternalDataReferences(externalRows);" in body
    assert "Showing cached snapshot." in body


def test_refresh_external_data_uses_dedicated_status_element() -> None:
    """External refresh should update only the external-data status text."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function refreshExternalDataReferences()")

    assert 'refreshExternalDataBtn.disabled = true;' in body
    assert 'loadIndustryBtn.disabled = true;' not in body
    assert 'loadIndustryBtn.disabled = false;' not in body
    assert "externalDataStatusEl.textContent = \"Refreshing external data...\";" in body
    assert "industryStatusEl.textContent = \"Refreshing external data...\";" not in body


def test_external_reference_table_marks_cached_rows_as_warning_state() -> None:
    """Cached fallback rows should render as warning badges instead of hard failures."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "function renderExternalDataReferences(rows)")

    assert 'row.status === "cached"' in body
    assert 'row.status === "proxy" || row.status === "dns_failed" || row.status === "cached"' in body


def test_industry_table_includes_as_of_column() -> None:
    """Industry table should expose per-row extraction dates."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "<th>As Of</th>" in source

    body = _function_body(source, "function renderIndustryRows(rows)")
    assert "${row.as_of ?? \"-\"}" in body


def test_industry_table_humanizes_internal_source_codes() -> None:
    """Industry rows should render readable source labels instead of internal fetcher ids."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "function humanizeSourceLabel(source)" in source
    assert '["spot_hog_lean_price_soozhu", "搜猪网"]' in source
    assert '["moa_market_info", "农业农村部"]' in source

    body = _function_body(source, "function renderIndustryRows(rows)")
    assert "humanizeSourceLabel(row.source || \"-\")" in body
