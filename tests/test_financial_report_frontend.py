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
    assert 'id="refreshExternalDataBtn"' in source
    assert "External Data References" in source
    assert "cached weekly snapshots" in source
    assert "function renderExternalDataReferences(rows)" in source
    assert "async function refreshExternalDataReferences()" in source
    assert "data.external_rows || []" in source
    assert "/industry_cycles?refresh=true&refresh_external=false" in source
    assert "/industry_cycles?refresh=false&refresh_external=true" in source
