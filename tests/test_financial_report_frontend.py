from __future__ import annotations

import re
from pathlib import Path

from starlette.routing import Mount

from app.main import app

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "index.html"
INDEX_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "index.js"
REPORT_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "report.js"
STOCK_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "stock.js"
INDUSTRY_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "industry.js"
MACRO_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "macro.js"
CORE_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "core.js"


def _template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _index_js_source() -> str:
    return INDEX_JS_PATH.read_text(encoding="utf-8")


def _report_js_source() -> str:
    return REPORT_JS_PATH.read_text(encoding="utf-8")


def _stock_js_source() -> str:
    return STOCK_JS_PATH.read_text(encoding="utf-8")


def _industry_js_source() -> str:
    return INDUSTRY_JS_PATH.read_text(encoding="utf-8")


def _macro_js_source() -> str:
    return MACRO_JS_PATH.read_text(encoding="utf-8")


def _core_js_source() -> str:
    return CORE_JS_PATH.read_text(encoding="utf-8")


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


def test_auto_read_annual_report_only_resets_when_symbol_changes() -> None:
    """Auto-read should preserve current results for the same symbol and clear only when the symbol changes."""
    source = _report_js_source()
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert "let activeRenderedReportSymbol = null;" in source
    assert "const shouldResetPanel = activeRenderedReportSymbol !== code;" in body
    assert "if (shouldResetPanel) {" in body
    assert "resetFinancialReportPanel();" in body


def test_auto_read_annual_report_has_empty_state_for_missing_report_source() -> None:
    """Auto-read should explain when no annual-report source metadata is available."""
    source = _report_js_source()
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert re.search(r"Report source metadata unavailable", body)


def test_financial_report_template_includes_llm_settings_panel_hooks() -> None:
    """Financial Reports UI should expose LLM settings controls and mode/status placeholders."""
    source = _template_source()

    assert 'id="llmApiKeyInput"' in source
    assert 'id="llmBaseUrlInput"' in source
    assert 'id="llmModelInput"' in source
    assert 'id="saveLlmSessionBtn"' in source
    assert 'id="testLlmConnectionBtn"' in source
    assert 'id="reportCurrentMode"' in source
    assert 'id="reportLlmStatus"' in source
    assert 'id="reportLlmAnalysis"' in source
    assert '<script type="module" src="/static/js/index.js"></script>' in source


def test_financial_report_template_includes_report_snapshot_panel_hooks() -> None:
    source = _template_source()

    assert 'id="reportSnapshotSections"' in source
    assert "function renderFinancialReportSnapshot(snapshot)" in _report_js_source()


def test_financial_report_template_includes_report_qa_panel() -> None:
    source = _template_source()

    assert 'id="reportQaSection"' in source
    assert 'id="reportQaSessionLabel"' in source
    assert 'id="reportQaChipList"' in source
    assert 'id="reportQaOlderToggle"' in source
    assert 'id="reportQaTranscript"' in source
    assert 'id="reportQaInput"' in source
    assert 'id="reportQaAskBtn"' in source


def test_financial_report_template_includes_guided_question_chips() -> None:
    source = _report_js_source()

    assert "今年利润增长主要来自哪里？" in source
    assert "经营现金流和净利润匹配吗？" in source
    assert "资本开支压力大吗？" in source


def test_financial_report_template_includes_report_qa_session_hooks() -> None:
    source = _report_js_source()

    assert "let reportQaSession" in source
    assert "let reportQaShowOlderTurns = false;" in source
    assert "resetReportQaSession" in source
    assert "reportQaSession = {" in source
    assert "Started a new Q&A session for the active report." in source
    assert "report_key" in source


def test_financial_report_template_includes_report_qa_ask_flow() -> None:
    source = _report_js_source()
    body = _function_body(source, "async function askActiveReport()")

    assert 'fetch(`${apiBase}/api/financial-report-qa`' in body
    assert 'appendReportQaTurn("user", question);' in body
    assert "history: reportQaSession.history.slice(-6).map" in body
    assert "evidence: Array.isArray(turn.evidence) ? turn.evidence : []" in body
    assert "citations: Array.isArray(turn.citations) ? turn.citations : []" in body
    assert "reportQaSession.sessionSummary" in body
    assert "updated_session_summary" in body
    assert "renderReportQaTranscript" in body


def test_financial_report_template_keeps_full_transcript_and_renders_older_toggle() -> None:
    source = _report_js_source()
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
    source = _report_js_source()

    assert "function formatReportQaRichText(value)" in source
    assert ".replace(/\\*\\*(.+?)\\*\\*/g, \"<strong>$1</strong>\")" in source
    assert 'bodyEl.innerHTML = formatReportQaRichText(turn.content || "-");' in source


def test_financial_report_template_rolls_back_user_turn_when_qa_request_fails() -> None:
    source = _report_js_source()
    body = _function_body(source, "async function askActiveReport()")

    assert "const previousHistorySnapshot = reportQaSession.history.map((turn) => ({ ...turn }));" in body
    assert "reportQaSession.history = previousHistorySnapshot;" in body


def test_financial_report_template_ignores_enter_during_ime_composition() -> None:
    source = _report_js_source()

    assert 'if (e.key === "Enter" && !e.isComposing) askActiveReport();' in source


def test_financial_report_url_analysis_sends_symbol_with_report_url() -> None:
    source = _report_js_source()
    body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")

    assert 'const reportSymbol = /^\\d{6}$/.test(reportCodeInput.value.trim()) ? reportCodeInput.value.trim() : null;' in body
    assert "force_refresh: forceRefresh" in body


def test_financial_report_url_analysis_resets_report_qa_before_fetch() -> None:
    source = _report_js_source()
    body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)


def test_report_flows_render_report_snapshot_sections() -> None:
    source = _report_js_source()
    report_body = _function_body(source, "async function loadFinancialReport(refresh = false)")
    url_body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")
    autoread_body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in report_body
    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in url_body
    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in autoread_body


def test_report_snapshot_renderer_displays_origin_and_display_unit_metadata() -> None:
    source = _report_js_source()
    body = _function_body(source, "function renderFinancialReportSnapshot(snapshot)")

    assert "formatReportSnapshotOrigin(item)" in source
    assert "formatReportSnapshotUnit(item)" in source
    assert 'Context fallback' in source
    assert 'Derived' in source
    assert 'Extracted' in source
    assert '${escapeHtml(formatReportSnapshotUnit(item))}' in body
    assert '${escapeHtml(formatReportSnapshotOrigin(item))}' in body


def test_report_snapshot_renderer_shows_formula_when_present() -> None:
    source = _report_js_source()
    body = _function_body(source, "function renderFinancialReportSnapshot(snapshot)")

    assert 'item.formula' in body
    assert 'formula' in body


def test_auto_read_resets_report_qa_before_fetch() -> None:
    source = _report_js_source()
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)


def test_financial_report_template_uses_report_key_only_for_active_session() -> None:
    source = _report_js_source()

    assert "data.report_key || data.session_key" not in source
    assert "const reportKey = data.report_key || null;" in source


def test_stock_and_report_panels_expose_explicit_refresh_controls() -> None:
    source = _template_source()

    assert 'id="refreshSingleStockBtn"' in source
    assert 'id="refreshWatchlistBtn"' in source
    assert 'id="refreshReportBtn"' in source
    assert 'id="forceReReadReportBtn"' in source


def test_stock_and_report_requests_include_refresh_flags_when_requested() -> None:
    source = _report_js_source()

    report_body = _function_body(source, "async function loadFinancialReport(refresh = false)")
    autoread_body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert "financial-report-analysis?symbol=" in report_body
    assert "&refresh=${refresh ? \"true\" : \"false\"}" in report_body
    assert "force_refresh=${forceRefresh ? \"true\" : \"false\"}" in autoread_body


def test_analyze_single_stock_renders_cached_tables_without_triggering_new_realtime_fetch() -> None:
    source = _stock_js_source()
    body = _function_body(source, "async function analyzeSingleStock(refresh = false)")

    assert "Promise.all([" not in body
    assert "renderPriceRows(currentPriceRows);" in body
    assert "renderFinancialRows(currentFinancialRows);" in body
    assert "maybeLoadMetricPanel();" in body
    assert "void loadSingleStockRealtime();" not in body
    assert "realtimeStatusEl.textContent =" in body
    assert '"Realtime quote will update on the next background refresh."' in body
    assert '"Using historical latest close until background realtime refresh."' in body
    assert "if (latestRealtimeSnapshotData) {" in body
    assert "applyCachedSingleRealtimeSnapshot();" in body


def test_async_single_stock_helpers_exist_for_metric_and_realtime_enrichment() -> None:
    source = _stock_js_source()

    lazy_metric_body = _function_body(source, "function maybeLoadMetricPanel()")
    metric_body = _function_body(source, "async function loadStockMetricPanel(symbol)")
    realtime_body = _function_body(source, "async function loadSingleStockRealtime()")
    failure_body = _function_body(source, "function applyRealtimeSnapshotFailure()")

    assert "Expand Metric Percentile Panel to load percentile history." in lazy_metric_body
    assert 'stockMetricStatusEl.textContent = "Loading metric percentile panel...";' in lazy_metric_body
    assert "/stock_metrics?symbol=" in metric_body
    assert "requestSharedRealtimeSnapshot" in realtime_body
    assert "Metric history refreshing in background." in metric_body
    assert "Metric panel warming in background; history not ready yet." in metric_body
    assert "Realtime quote unavailable; using historical latest close." in failure_body


def test_analyze_watchlist_renders_cached_rows_without_triggering_new_realtime_fetch() -> None:
    source = _stock_js_source()
    body = _function_body(source, "async function analyzeWatchlist(refresh = false)")

    assert "renderWatchlistRows(rows);" in body
    assert "void loadWatchlistRealtime(" not in body
    assert '`${baseStatusText} Realtime will update on the next background refresh.`' in body
    assert '`${baseStatusText} Using cached watchlist snapshot until background realtime refresh.`' in body
    assert "const unresolvedNameSymbols = watchlistSymbolsMissingNames(watchlistSymbols);" in body


def test_financial_report_template_uses_external_js_entrypoint() -> None:
    source = _template_source()

    assert '<script type="module" src="/static/js/index.js"></script>' in source
    assert "<script>" not in source


def test_static_js_entrypoint_is_served() -> None:
    static_mounts = [
        route for route in app.routes if isinstance(route, Mount) and getattr(route, "path", None) == "/static"
    ]

    assert static_mounts
    assert INDEX_JS_PATH.exists()
    assert REPORT_JS_PATH.exists()
    assert "async function autoReadAnnualReport(forceRefresh = false)" in _report_js_source()


def test_index_js_imports_report_module() -> None:
    source = _index_js_source()

    assert 'from "./report.js"' in source
    assert "setupReportModule(" in source


def test_index_js_imports_stock_module() -> None:
    source = _index_js_source()

    assert 'from "./stock.js"' in source
    assert "setupStockModule(" in source


def test_report_js_module_exists() -> None:
    assert REPORT_JS_PATH.exists()


def test_stock_js_module_exists() -> None:
    assert STOCK_JS_PATH.exists()


def test_index_js_imports_industry_module() -> None:
    source = _index_js_source()

    assert 'from "./industry.js"' in source
    assert "setupIndustryModule(" in source


def test_industry_js_module_exists() -> None:
    assert INDUSTRY_JS_PATH.exists()


def test_index_js_imports_macro_module() -> None:
    source = _index_js_source()

    assert 'from "./macro.js"' in source
    assert "setupMacroModule(" in source


def test_index_js_imports_core_module() -> None:
    source = _index_js_source()

    assert 'from "./core.js"' in source


def test_macro_js_module_exists() -> None:
    assert MACRO_JS_PATH.exists()


def test_core_js_module_exists() -> None:
    assert CORE_JS_PATH.exists()


def test_macro_module_loads_rows_and_signals_together() -> None:
    source = _macro_js_source()
    body = _function_body(source, "async function loadMacroIndicators()")

    assert "/api/macro-indicators?table=" in body
    assert "/macro_signals?table=" in body
    assert "Promise.all([fetch(rowsUrl), fetch(signalsUrl)])" in body
    assert "renderMacroRows(viewRows);" in body
    assert "renderMacroSignals(signalData || []);" in body
    assert "renderValuationPanel(signalData || []);" in body


def test_macro_module_supports_fill_missing_and_valuation_empty_state() -> None:
    source = _macro_js_source()

    assert "function fillMissingValues(rows)" in source
    assert "function buildMissingHint(rows)" in source
    assert 'macroFillMissing.addEventListener("change", () =>' in source
    assert 'macroHintEl.textContent = "No rows found in selected table/limit."; ' not in source
    assert 'macroHintEl.textContent = "No rows found in selected table/limit.";' in source
    assert "No Data" in source


def test_market_supplemental_fetches_use_frontend_timeout_guards() -> None:
    source = _stock_js_source()
    core_source = _core_js_source()

    assert "async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000, errorLabel = \"Backend\")" in core_source
    shared_realtime_body = _function_body(source, "async function requestSharedRealtimeSnapshot(symbols)")
    watchlist_name_body = _function_body(source, "async function loadWatchlistNames(symbols, requestToken)")

    metric_body = _function_body(source, "async function loadStockMetricPanel(symbol)")
    single_realtime_body = _function_body(source, "async function loadSingleStockRealtime()")

    assert "fetchJsonWithTimeout(" in metric_body
    assert "fetchJsonWithTimeout(" in shared_realtime_body
    assert "fetchJsonWithTimeout(" in watchlist_name_body
    assert "requestSharedRealtimeSnapshot(" in single_realtime_body
    assert "/api/stock-names?symbols=" in watchlist_name_body
    assert "Metric panel unavailable:" in metric_body
    assert "Realtime quote unavailable; showing cached watchlist snapshot." in source


def test_metric_panel_lazy_loads_on_accordion_open() -> None:
    stock_source = _stock_js_source()
    index_source = _index_js_source()

    assert "const metricAccordionToggleEl = document.querySelector('[aria-controls=\"metricAccordionBody\"]');" in stock_source
    assert "let stockMetricLoadedSymbol = null;" in stock_source
    assert "let stockMetricLoadingSymbol = null;" in stock_source
    accordion_body = _function_body(index_source, "buttonEl.addEventListener(\"click\", () =>")

    assert 'if (bodyId === "metricAccordionBody" && !isExpanded) {' in accordion_body
    assert "maybeLoadMetricPanel();" in accordion_body


def test_warning_summaries_use_short_labels_in_status_text() -> None:
    source = _core_js_source()
    stock_source = _stock_js_source()

    assert "function summarizeWarnings(warnings)" in source
    assert 'return summarized.length ? ` Warnings: ${summarized.join(" | ")}` : "";' in source
    assert "const warningText = summarizeWarnings(data.warnings || []);" in stock_source


def test_realtime_polling_skips_hidden_tabs_and_overlapping_requests() -> None:
    source = _stock_js_source()
    body = _function_body(source, "async function refreshRealtimePrices()")

    assert "let realtimeRefreshInFlight = false;" in source
    assert "let latestRealtimeSnapshotData = null;" in source
    assert "let realtimeRequestPromise = null;" in source
    assert "let queuedRealtimeSymbols = new Set();" in source
    assert 'document.visibilityState !== "visible"' in body
    assert "if (realtimeRefreshInFlight) return;" in body
    assert "realtimeRefreshInFlight = true;" in body
    assert "realtimeRefreshInFlight = false;" in body
    assert "setInterval(refreshRealtimePrices, 60000);" in source


def test_shared_realtime_scheduler_batches_requests_and_replays_queued_symbols() -> None:
    source = _stock_js_source()
    body = _function_body(source, "async function requestSharedRealtimeSnapshot(symbols)")

    assert "queuedRealtimeSymbols.add(symbol);" in body
    assert "if (realtimeRequestPromise) return realtimeRequestPromise;" in body
    assert "const requestedSymbols = [...queuedRealtimeSymbols];" in body
    assert "queuedRealtimeSymbols.clear();" in body
    assert "latestRealtimeSnapshotData = data;" in body
    assert "if (queuedRealtimeSymbols.size) {" in body


def test_report_url_helper_copy_is_limited_to_official_disclosure_links() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "official disclosure links only" in source.lower()


def test_dashboard_template_includes_external_data_reference_section() -> None:
    """Dashboard UI should expose the external-data table and render rows from industry payloads."""
    source = _template_source()
    js_source = _industry_js_source()

    assert 'id="externalDataTable"' in source
    assert 'id="externalDataStatus"' in source
    assert 'id="refreshExternalDataBtn"' in source
    assert "External Data References" in source
    assert "cached weekly snapshots" in source
    assert "function renderExternalDataReferences(rows)" in js_source
    assert "async function loadCachedIndustryCycles()" in js_source
    assert "async function refreshExternalDataReferences()" in js_source
    assert "data.external_rows || []" in js_source
    assert "/industry_cycles?refresh=true&refresh_external=false" in js_source
    assert "/industry_cycles?refresh=false&refresh_external=false" in js_source
    assert "/industry_cycles?refresh=false&refresh_external=true" in js_source


def test_load_industry_cycles_does_not_touch_external_reference_table() -> None:
    """Industry refresh should not clear or rerender the external reference table."""
    source = _industry_js_source()
    body = _function_body(source, "async function loadIndustryCycles()")

    assert 'loadIndustryBtn.disabled = true;' in body
    assert 'refreshExternalDataBtn.disabled = true;' not in body
    assert 'refreshExternalDataBtn.disabled = false;' not in body
    assert "renderIndustryRows(rows);" in body
    assert "renderExternalDataReferences(data.external_rows || []);" not in body
    assert "externalDataTableBody.innerHTML = \"\";" not in body


def test_load_cached_industry_cycles_reads_cache_and_renders_both_tables() -> None:
    """Initial industry-tab load should read cached data and render both tables."""
    source = _industry_js_source()
    body = _function_body(source, "async function loadCachedIndustryCycles()")

    assert "/industry_cycles?refresh=false&refresh_external=false" in body
    assert "renderIndustryRows(rows);" in body
    assert "renderExternalDataReferences(externalRows);" in body
    assert "Showing cached snapshot." in body


def test_refresh_external_data_uses_dedicated_status_element() -> None:
    """External refresh should update only the external-data status text."""
    source = _industry_js_source()
    body = _function_body(source, "async function refreshExternalDataReferences()")

    assert 'refreshExternalDataBtn.disabled = true;' in body
    assert 'loadIndustryBtn.disabled = true;' not in body
    assert 'loadIndustryBtn.disabled = false;' not in body
    assert "externalDataStatusEl.textContent = \"Refreshing external data...\";" in body
    assert "industryStatusEl.textContent = \"Refreshing external data...\";" not in body


def test_external_reference_table_marks_cached_rows_as_warning_state() -> None:
    """Cached fallback rows should render as warning badges instead of hard failures."""
    source = _industry_js_source()
    body = _function_body(source, "function renderExternalDataReferences(rows)")

    assert 'row.status === "cached"' in body
    assert 'row.status === "proxy" || row.status === "dns_failed" || row.status === "cached"' in body


def test_industry_table_uses_indicator_as_of_column_label() -> None:
    """Industry table should clarify that each row carries its own observation date."""
    source = _template_source()
    js_source = _industry_js_source()

    assert "<th>Indicator As Of</th>" in source

    body = _function_body(js_source, "function renderIndustryRows(rows)")
    assert "${row.as_of ?? \"-\"}" in body


def test_industry_table_renders_source_links_from_payload() -> None:
    """Industry rows should render upstream links without hardcoding source-specific URL logic in the template."""
    source = _template_source()
    js_source = _industry_js_source()

    assert "<th>Link</th>" in source
    body = _function_body(js_source, "function renderIndustryRows(rows)")
    assert "row.source_url" in body
    assert 'target="_blank" rel="noreferrer">Open</a>' in body


def test_industry_table_prefers_display_name_over_internal_key() -> None:
    """Industry rows should render human-readable indicator labels in the table."""
    body = _function_body(_industry_js_source(), "function renderIndustryRows(rows)")

    assert "${row.display_name ?? row.indicator ?? \"-\"}" in body


def test_load_industry_cycles_keeps_existing_rows_visible_during_refresh() -> None:
    """Live industry refresh should not clear the table before the new payload arrives."""
    source = _industry_js_source()
    body = _function_body(source, "async function loadIndustryCycles()")

    assert 'industryStatusEl.textContent = "Loading industry cycles...";' in body
    assert 'industryTableBody.innerHTML = "";' not in body


def test_industry_status_text_mentions_refreshed_at_timestamp() -> None:
    """Industry status text should distinguish indicator dates from the current refresh time."""
    source = _industry_js_source()
    load_body = _function_body(source, "async function loadIndustryCycles()")
    cached_body = _function_body(source, "async function loadCachedIndustryCycles()")

    assert "Refreshed at:" in load_body
    assert "Refreshed at:" in cached_body
