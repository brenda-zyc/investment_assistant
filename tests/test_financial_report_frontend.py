from __future__ import annotations

import re
from pathlib import Path


TEMPLATE_PATH = Path("/Users/brenda/Projects/investment_assistant/app/templates/index.html")


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
