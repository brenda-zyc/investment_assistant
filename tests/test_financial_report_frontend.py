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
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    reset_call = "resetFinancialReportPanel();"
    assert reset_call in body

    reset_index = body.index(reset_call)
    fetch_index = body.index("const res = await fetch(")
    assert reset_index < fetch_index


def test_auto_read_annual_report_has_empty_state_for_missing_report_source() -> None:
    """Auto-read should explain when no annual-report source metadata is available."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

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


def test_financial_report_template_includes_report_snapshot_panel_hooks() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="reportSnapshotSections"' in source
    assert "function renderFinancialReportSnapshot(snapshot)" in source


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
    assert "evidence: Array.isArray(turn.evidence) ? turn.evidence : []" in body
    assert "citations: Array.isArray(turn.citations) ? turn.citations : []" in body
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
    body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")

    assert 'const reportSymbol = /^\\d{6}$/.test(reportCodeInput.value.trim()) ? reportCodeInput.value.trim() : null;' in body
    assert "force_refresh: forceRefresh" in body


def test_financial_report_url_analysis_resets_report_qa_before_fetch() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)


def test_report_flows_render_report_snapshot_sections() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    report_body = _function_body(source, "async function loadFinancialReport(refresh = false)")
    url_body = _function_body(source, "async function loadFinancialReportFromUrl(forceRefresh = false)")
    autoread_body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in report_body
    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in url_body
    assert "renderFinancialReportSnapshot(data.report_snapshot || null);" in autoread_body


def test_auto_read_resets_report_qa_before_fetch() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    reset_call = "resetReportQaSession("
    fetch_call = "const res = await fetch("
    assert reset_call in body
    assert body.index(reset_call) < body.index(fetch_call)


def test_financial_report_template_uses_report_key_only_for_active_session() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "data.report_key || data.session_key" not in source
    assert "const reportKey = data.report_key || null;" in source


def test_stock_and_report_panels_expose_explicit_refresh_controls() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'id="refreshSingleStockBtn"' in source
    assert 'id="refreshWatchlistBtn"' in source
    assert 'id="refreshReportBtn"' in source
    assert 'id="forceReReadReportBtn"' in source


def test_stock_and_report_requests_include_refresh_flags_when_requested() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    single_body = _function_body(source, "async function analyzeSingleStock(refresh = false)")
    watchlist_body = _function_body(source, "async function analyzeWatchlist(refresh = false)")
    report_body = _function_body(source, "async function loadFinancialReport(refresh = false)")
    autoread_body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")

    assert "body: JSON.stringify({ stock_code: code, refresh })" in single_body
    assert "body: JSON.stringify({ stock_codes: codes, refresh })" in watchlist_body
    assert "financial-report-analysis?symbol=" in report_body
    assert "&refresh=${refresh ? \"true\" : \"false\"}" in report_body
    assert "force_refresh=${forceRefresh ? \"true\" : \"false\"}" in autoread_body


def test_analyze_single_stock_renders_cached_tables_without_triggering_new_realtime_fetch() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function analyzeSingleStock(refresh = false)")

    assert "Promise.all([" not in body
    assert "renderPriceRows(currentPriceRows);" in body
    assert "renderFinancialRows(currentFinancialRows);" in body
    assert "maybeLoadMetricPanel();" in body
    assert "void loadSingleStockRealtime();" not in body
    assert 'refresh\n              ? "Realtime quote will update on the next background refresh."\n              : "Using historical latest close until background realtime refresh."' in body
    assert "if (latestRealtimeSnapshotData) {" in body
    assert "applyCachedSingleRealtimeSnapshot();" in body


def test_async_single_stock_helpers_exist_for_metric_and_realtime_enrichment() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

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
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function analyzeWatchlist(refresh = false)")

    assert "renderWatchlistRows(rows);" in body
    assert "void loadWatchlistRealtime(" not in body
    assert '`${baseStatusText} Realtime will update on the next background refresh.`' in body
    assert '`${baseStatusText} Using cached watchlist snapshot until background realtime refresh.`' in body
    assert "const unresolvedNameSymbols = watchlistSymbolsMissingNames(watchlistSymbols);" in body
    assert "void loadWatchlistNames(unresolvedNameSymbols, requestToken);" in body
    assert "if (latestRealtimeSnapshotData) {" in body
    assert "applyCachedWatchlistRealtimeSnapshot();" in body
    assert body.index("applyCachedWatchlistRealtimeSnapshot();") < body.index("watchlistSymbolsMissingNames")


def test_market_supplemental_fetches_use_frontend_timeout_guards() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000, errorLabel = \"Backend\")" in source
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
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "const metricAccordionToggleEl = document.querySelector('[aria-controls=\"metricAccordionBody\"]');" in source
    assert "let stockMetricLoadedSymbol = null;" in source
    assert "let stockMetricLoadingSymbol = null;" in source
    accordion_body = _function_body(source, "buttonEl.addEventListener(\"click\", () =>")

    assert 'if (bodyId === "metricAccordionBody" && !isExpanded) {' in accordion_body
    assert "maybeLoadMetricPanel();" in accordion_body


def test_warning_summaries_use_short_labels_in_status_text() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "function summarizeWarnings(warnings)" in source
    assert 'return summarized.length ? ` Warnings: ${summarized.join(" | ")}` : "";' in source
    assert "const warningText = summarizeWarnings(data.warnings || []);" in source


def test_realtime_polling_skips_hidden_tabs_and_overlapping_requests() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
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
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
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


def test_industry_table_uses_indicator_as_of_column_label() -> None:
    """Industry table should clarify that each row carries its own observation date."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "<th>Indicator As Of</th>" in source

    body = _function_body(source, "function renderIndustryRows(rows)")
    assert "${row.as_of ?? \"-\"}" in body


def test_industry_table_renders_source_links_from_payload() -> None:
    """Industry rows should render upstream links without hardcoding source-specific URL logic in the template."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "<th>Link</th>" in source
    body = _function_body(source, "function renderIndustryRows(rows)")
    assert "row.source_url" in body
    assert 'target="_blank" rel="noreferrer">Open</a>' in body


def test_industry_table_prefers_display_name_over_internal_key() -> None:
    """Industry rows should render human-readable indicator labels in the table."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "function renderIndustryRows(rows)")

    assert "${row.display_name ?? row.indicator ?? \"-\"}" in body


def test_load_industry_cycles_keeps_existing_rows_visible_during_refresh() -> None:
    """Live industry refresh should not clear the table before the new payload arrives."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function loadIndustryCycles()")

    assert 'industryStatusEl.textContent = "Loading industry cycles...";' in body
    assert 'industryTableBody.innerHTML = "";' not in body


def test_industry_status_text_mentions_refreshed_at_timestamp() -> None:
    """Industry status text should distinguish indicator dates from the current refresh time."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    load_body = _function_body(source, "async function loadIndustryCycles()")
    cached_body = _function_body(source, "async function loadCachedIndustryCycles()")

    assert "Refreshed at:" in load_body
    assert "Refreshed at:" in cached_body
