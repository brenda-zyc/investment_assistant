import { setupReportModule } from "./report.js";

      const apiBase =
        window.location.protocol === "http:" || window.location.protocol === "https:"
          ? window.location.origin
          : "http://127.0.0.1:8000";

      const tabStockBtn = document.getElementById("tabStockBtn");
      const tabMacroBtn = document.getElementById("tabMacroBtn");
      const tabIndustryBtn = document.getElementById("tabIndustryBtn");
      const tabReportBtn = document.getElementById("tabReportBtn");
      const stockPanel = document.getElementById("stockPanel");
      const macroPanel = document.getElementById("macroPanel");
      const industryPanel = document.getElementById("industryPanel");
      const reportPanel = document.getElementById("reportPanel");

      const analyzeBtn = document.getElementById("analyzeBtn");
      const refreshSingleStockBtn = document.getElementById("refreshSingleStockBtn");
      const stockCodeInput = document.getElementById("stockCode");
      const singleStatusEl = document.getElementById("singleStatus");
      const realtimeStatusEl = document.getElementById("realtimeStatus");

      const metricSymbol = document.getElementById("metricSymbol");
      const metricClose = document.getElementById("metricClose");
      const metricChange = document.getElementById("metricChange");
      const metricQuality = document.getElementById("metricQuality");
      const metricAccordionToggleEl = document.querySelector('[aria-controls="metricAccordionBody"]');
      const metricAccordionBodyEl = document.getElementById("metricAccordionBody");

      const priceLimitSelect = document.getElementById("priceLimitSelect");
      const priceTableBody = document.querySelector("#priceTable tbody");
      const priceMetaEl = document.getElementById("priceMeta");
      const financialTableBody = document.querySelector("#financialTable tbody");

      const watchlistCodes = document.getElementById("watchlistCodes");
      const analyzeWatchlistBtn = document.getElementById("analyzeWatchlistBtn");
      const refreshWatchlistBtn = document.getElementById("refreshWatchlistBtn");
      const watchlistStatusEl = document.getElementById("watchlistStatus");
      const watchlistTableBody = document.querySelector("#watchlistTable tbody");

      const macroTableSelect = document.getElementById("macroTableSelect");
      const macroLimitInput = document.getElementById("macroLimitInput");
      const macroFillMissing = document.getElementById("macroFillMissing");
      const loadMacroBtn = document.getElementById("loadMacroBtn");
      const macroStatusEl = document.getElementById("macroStatus");
      const macroHintEl = document.getElementById("macroHint");
      const valuationPanelEl = document.getElementById("valuationPanel");
      const macroSignalTableBody = document.querySelector("#macroSignalTable tbody");
      const macroTableHead = document.querySelector("#macroTable thead");
      const macroTableBody = document.querySelector("#macroTable tbody");
      const stockMetricTableBody = document.querySelector("#stockMetricTable tbody");
      const stockMetricStatusEl = document.getElementById("stockMetricStatus");
      const externalDataTableBody = document.querySelector("#externalDataTable tbody");
      const externalDataStatusEl = document.getElementById("externalDataStatus");
      const loadIndustryBtn = document.getElementById("loadIndustryBtn");
      const refreshExternalDataBtn = document.getElementById("refreshExternalDataBtn");
      const industryStatusEl = document.getElementById("industryStatus");
      const industryTableBody = document.querySelector("#industryTable tbody");
      const reportCodeInput = document.getElementById("reportCode");
      const loadReportBtn = document.getElementById("loadReportBtn");
      const refreshReportBtn = document.getElementById("refreshReportBtn");
      const autoReadReportBtn = document.getElementById("autoReadReportBtn");
      const forceReReadReportBtn = document.getElementById("forceReReadReportBtn");
      const reportUrlInput = document.getElementById("reportUrlInput");
      const analyzeReportUrlBtn = document.getElementById("analyzeReportUrlBtn");
      const llmProviderInput = document.getElementById("llmProviderInput");
      const llmBaseUrlInput = document.getElementById("llmBaseUrlInput");
      const llmModelInput = document.getElementById("llmModelInput");
      const llmApiKeyInput = document.getElementById("llmApiKeyInput");
      const saveLlmSessionBtn = document.getElementById("saveLlmSessionBtn");
      const testLlmConnectionBtn = document.getElementById("testLlmConnectionBtn");
      const llmSessionStatusEl = document.getElementById("llmSessionStatus");
      const reportStatusEl = document.getElementById("reportStatus");
      const reportSourceMetaEl = document.getElementById("reportSourceMeta");
      const reportCurrentModeEl = document.getElementById("reportCurrentMode");
      const reportLlmStatusEl = document.getElementById("reportLlmStatus");
      const reportMetricYearEl = document.getElementById("reportMetricYear");
      const reportMetricScoreEl = document.getElementById("reportMetricScore");
      const reportMetricRevenueYoyEl = document.getElementById("reportMetricRevenueYoy");
      const reportMetricProfitYoyEl = document.getElementById("reportMetricProfitYoy");
      const reportSnapshotMetaEl = document.getElementById("reportSnapshotMeta");
      const reportSnapshotSectionsEl = document.getElementById("reportSnapshotSections");
      const reportInsightListEl = document.getElementById("reportInsightList");
      const reportAutoreadListEl = document.getElementById("reportAutoreadList");
      const reportLlmAnalysisEl = document.getElementById("reportLlmAnalysis");
      const reportQaSessionLabelEl = document.getElementById("reportQaSessionLabel");
      const reportQaChipListEl = document.getElementById("reportQaChipList");
      const reportQaOlderToggleEl = document.getElementById("reportQaOlderToggle");
      const reportQaTranscriptEl = document.getElementById("reportQaTranscript");
      const reportQaInputEl = document.getElementById("reportQaInput");
      const reportQaAskBtn = document.getElementById("reportQaAskBtn");
      const reportEvidenceListEl = document.getElementById("reportEvidenceList");
      const reportDetailTableBody = document.querySelector("#reportDetailTable tbody");

      let currentPriceRows = [];
      let currentFinancialRows = [];
      let currentSymbol = null;
      let currentSymbolName = null;
      let stockMetricLoadedSymbol = null;
      let stockMetricLoadingSymbol = null;
      let latestRealtimeSnapshotData = null;
      let realtimeRefreshInFlight = false;
      let realtimeRequestPromise = null;
      let queuedRealtimeSymbols = new Set();
      let inFlightRealtimeSymbols = new Set();
      let watchlistSymbols = [];
      let watchlistRequestToken = 0;
      let latestWatchlistRealtimeBaseStatus = "";
      let latestWatchlistRealtimeRequestToken = 0;
      let lastMacroRows = [];
      let macroLoadedOnce = false;
      let industryLoadedOnce = false;
      let reportLoadedOnce = false;
      const macroTableLabelMap = {
        macro_indicators: "Production Macro (macro_indicators)",
        macro_indicators_step1: "Core Macro (5 indicators)",
        macro_indicators_step2: "Full Macro (10 indicators)",
      };
      const valuationIndicatorConfig = [
        { key: "shanghai_composite_pe", label: "Shanghai Composite PE" },
        { key: "csi300_pe", label: "CSI 300 PE" },
        { key: "chinext_pe", label: "ChiNext PE" },
        { key: "star_market_pe", label: "STAR Market PE" },
        { key: "hang_seng_pe", label: "Hang Seng Index PE" },
        { key: "hang_seng_tech_pe", label: "Hang Seng Tech Index PE" },
      ];
      const reportModule = setupReportModule({
        apiBase,
        summarizeWarnings,
        formatNumber,
        formatPercent,
        escapeHtml,
        escapeHtmlAttribute,
        isBackendUnreachable,
        parseJsonResponse,
        dom: {
          reportCodeInput,
          loadReportBtn,
          refreshReportBtn,
          autoReadReportBtn,
          forceReReadReportBtn,
          reportUrlInput,
          analyzeReportUrlBtn,
          llmProviderInput,
          llmBaseUrlInput,
          llmModelInput,
          llmApiKeyInput,
          saveLlmSessionBtn,
          testLlmConnectionBtn,
          llmSessionStatusEl,
          reportStatusEl,
          reportSourceMetaEl,
          reportCurrentModeEl,
          reportLlmStatusEl,
          reportMetricYearEl,
          reportMetricScoreEl,
          reportMetricRevenueYoyEl,
          reportMetricProfitYoyEl,
          reportSnapshotMetaEl,
          reportSnapshotSectionsEl,
          reportInsightListEl,
          reportAutoreadListEl,
          reportLlmAnalysisEl,
          reportQaSessionLabelEl,
          reportQaChipListEl,
          reportQaOlderToggleEl,
          reportQaTranscriptEl,
          reportQaInputEl,
          reportQaAskBtn,
          reportEvidenceListEl,
          reportDetailTableBody,
        },
      });

      function switchTab(targetId) {
        const isStock = targetId === "stockPanel";
        const isMacro = targetId === "macroPanel";
        const isIndustry = targetId === "industryPanel";
        const isReport = targetId === "reportPanel";
        tabStockBtn.classList.toggle("active", isStock);
        tabMacroBtn.classList.toggle("active", isMacro);
        tabIndustryBtn.classList.toggle("active", isIndustry);
        tabReportBtn.classList.toggle("active", isReport);
        tabStockBtn.setAttribute("aria-selected", String(isStock));
        tabMacroBtn.setAttribute("aria-selected", String(isMacro));
        tabIndustryBtn.setAttribute("aria-selected", String(isIndustry));
        tabReportBtn.setAttribute("aria-selected", String(isReport));
        stockPanel.classList.toggle("active", isStock);
        macroPanel.classList.toggle("active", isMacro);
        industryPanel.classList.toggle("active", isIndustry);
        reportPanel.classList.toggle("active", isReport);

        if (isMacro && !macroLoadedOnce) {
          loadMacroIndicators();
          macroLoadedOnce = true;
        }
        if (isIndustry && !industryLoadedOnce) {
          loadCachedIndustryCycles();
          industryLoadedOnce = true;
        }
        if (isReport && !reportLoadedOnce) {
          if (currentSymbol) {
            reportCodeInput.value = currentSymbol;
            reportModule.loadFinancialReport();
          }
          reportLoadedOnce = true;
        }
      }

      tabStockBtn.addEventListener("click", () => switchTab("stockPanel"));
      tabMacroBtn.addEventListener("click", () => switchTab("macroPanel"));
      tabIndustryBtn.addEventListener("click", () => switchTab("industryPanel"));
      tabReportBtn.addEventListener("click", () => switchTab("reportPanel"));

      function formatNumber(value, digits = 2) {
        if (value === null || value === undefined || value === "") return "-";
        const n = Number(value);
        if (Number.isNaN(n)) return "-";
        return n.toLocaleString(undefined, { maximumFractionDigits: digits });
      }

      function formatPercent(value, digits = 2) {
        if (value === null || value === undefined || value === "") return "-";
        const n = Number(value);
        if (Number.isNaN(n)) return "-";
        return `${(n * 100).toLocaleString(undefined, { maximumFractionDigits: digits })}%`;
      }

      function escapeHtmlAttribute(value) {
        return String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/"/g, "&quot;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
      }

      function escapeHtml(value) {
        return String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
      }

      function isBackendUnreachable(err) {
        const message = String(err?.message || err || "").toLowerCase();
        return (
          err instanceof TypeError &&
          (message.includes("failed to fetch") || message.includes("networkerror") || message.includes("load failed"))
        );
      }

      async function parseJsonResponse(res, errorLabel = "Backend") {
        const bodyText = await res.text();
        try {
          return bodyText ? JSON.parse(bodyText) : {};
        } catch (_err) {
          throw new Error(`${errorLabel} returned non-JSON response (HTTP ${res.status}).`);
        }
      }

      async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000, errorLabel = "Backend") {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
          const response = await fetch(url, { ...options, signal: controller.signal });
          const data = await parseJsonResponse(response, errorLabel);
          return { response, data };
        } catch (err) {
          if (err?.name === "AbortError") {
            throw new Error(`${errorLabel} timed out after ${Math.round(timeoutMs / 1000)}s.`);
          }
          throw err;
        } finally {
          window.clearTimeout(timer);
        }
      }

      function resetMetrics() {
        metricSymbol.textContent = "-";
        metricClose.textContent = "-";
        metricChange.textContent = "-";
        metricChange.className = "value";
        metricQuality.textContent = "-";
      }

      function updateSingleRealtimeDisplay(quote) {
        if (!quote) return;
        const displaySymbol = quote.symbol || currentSymbol || "-";
        const displayName = quote.name || currentSymbolName;
        metricSymbol.textContent = displayName ? `${displaySymbol} ${displayName}` : displaySymbol;
        if (quote.latest_price !== null && quote.latest_price !== undefined) {
          metricClose.textContent = formatNumber(quote.latest_price);
        }
      }

      function updateMetrics(symbol, priceRows, financialRows) {
        metricSymbol.textContent = symbol || "-";

        const latest = priceRows[0];
        const prev = priceRows[1];
        if (latest && latest.close !== null && latest.close !== undefined) {
          metricClose.textContent = formatNumber(latest.close);
        } else {
          metricClose.textContent = "-";
        }

        if (latest && prev && latest.close != null && prev.close != null && Number(prev.close) !== 0) {
          const delta = Number(latest.close) - Number(prev.close);
          const pct = (delta / Number(prev.close)) * 100;
          metricChange.textContent = `${delta >= 0 ? "+" : ""}${formatNumber(delta)} (${pct >= 0 ? "+" : ""}${formatNumber(pct)}%)`;
          metricChange.className = `value ${delta >= 0 ? "num-up" : "num-down"}`;
        } else {
          metricChange.textContent = "-";
          metricChange.className = "value";
        }

        const latestFinancial = financialRows[0];
        if (latestFinancial) {
          metricQuality.textContent = `ROE ${formatNumber(latestFinancial.roe)}% / Debt ${formatNumber(latestFinancial.debt_ratio)}%`;
        } else {
          metricQuality.textContent = "-";
        }
      }

      function renderPriceRows(rows) {
        const limit = priceLimitSelect.value;
        const renderRows = limit === "all" ? rows : rows.slice(0, Number(limit));
        priceTableBody.innerHTML = "";

        renderRows.forEach((row, index) => {
          const previous = renderRows[index + 1];
          const upDownClass =
            previous && row.close != null && previous.close != null
              ? Number(row.close) >= Number(previous.close)
                ? "num-up"
                : "num-down"
              : "";

          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${row.trade_date ?? "-"}</td>
            <td>${formatNumber(row.open)}</td>
            <td class="${upDownClass}">${formatNumber(row.close)}</td>
            <td>${formatNumber(row.high)}</td>
            <td>${formatNumber(row.low)}</td>
            <td>${formatNumber(row.volume)}</td>
            <td>${formatNumber(row.amount)}</td>
          `;
          priceTableBody.appendChild(tr);
        });

        priceMetaEl.textContent = `Showing ${renderRows.length} / ${rows.length} rows.`;
      }

      function renderFinancialRows(rows) {
        financialTableBody.innerHTML = "";
        rows.forEach((row) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${row.report_year ?? "-"}</td>
            <td>${row.report_date ?? "-"}</td>
            <td>${formatNumber(row.revenue)}</td>
            <td>${formatNumber(row.net_profit)}</td>
            <td>${formatNumber(row.roe)}</td>
            <td>${formatNumber(row.debt_ratio)}</td>
          `;
          financialTableBody.appendChild(tr);
        });
      }

      function renderExternalDataReferences(rows) {
        externalDataTableBody.innerHTML = "";
        rows.forEach((row) => {
          const linkHtml = row.source_url
            ? `<a href="${escapeHtmlAttribute(row.source_url)}" target="_blank" rel="noreferrer">Open</a>`
            : "-";
          const statusClass =
            row.status === "ok"
              ? "ok"
              : row.status === "proxy" || row.status === "dns_failed" || row.status === "cached"
                ? "warn"
                : row.status === "fetch_failed"
                  ? "bad"
                  : "";
          const statusText = row.status || "-";
          const statusHtml = statusClass ? `<span class="status ${statusClass}">${statusText}</span>` : statusText;
          const noteText = row.error ? `${row.note || "-"} Error: ${row.error}` : row.note || "-";
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${row.display_name ?? row.indicator ?? "-"}</td>
            <td>${formatNumber(row.value, 4)}</td>
            <td>${row.as_of ?? "-"}</td>
            <td>${row.source ?? "-"}</td>
            <td>${linkHtml}</td>
            <td>${statusHtml}</td>
            <td class="note">${noteText}</td>
          `;
          externalDataTableBody.appendChild(tr);
        });
      }

      function buildIndustryWarningText(data) {
        return summarizeWarnings(data.warnings || []);
      }

      function latestAsOfFromRows(rows) {
        const asOfValues = (rows || []).map((row) => row?.as_of).filter(Boolean);
        if (!asOfValues.length) return "-";
        return asOfValues.sort().at(-1);
      }

      function metricDisplayName(name) {
        const mapping = {
          pe_ttm: "PE (TTM)",
          pb: "PB",
          roe: "ROE",
          roic: "ROIC",
          revenue_cagr_5y: "Revenue CAGR (5Y)",
        };
        return mapping[name] || name;
      }

      function renderStockMetricRows(metrics) {
        stockMetricTableBody.innerHTML = "";
        metrics.forEach((item) => {
          const percentileText = item.percentile == null ? "-" : `${item.percentile}%`;
          const fillWidth = item.percentile == null ? 0 : item.percentile;
          const hint =
            item.data_insufficient || item.percentile == null
              ? `<span class="tiny-note">data_insufficient (n=${item.sample_size ?? 0})</span>`
              : "";
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${metricDisplayName(item.name)}</td>
            <td>${formatNumber(item.value, 4)}</td>
            <td class="pct-cell">
              <div class="pct-wrap">
                <span>${percentileText}</span>
                <div class="pct-bar"><div class="pct-fill" style="width:${fillWidth}%"></div></div>
              </div>
              ${hint}
            </td>
          `;
          stockMetricTableBody.appendChild(tr);
        });
      }

      function isMetricAccordionOpen() {
        return (
          metricAccordionToggleEl &&
          metricAccordionToggleEl.getAttribute("aria-expanded") === "true" &&
          metricAccordionBodyEl &&
          !metricAccordionBodyEl.hidden
        );
      }

      function maybeLoadMetricPanel() {
        if (!currentSymbol) {
          stockMetricStatusEl.textContent = "Run Analysis to load metric percentiles.";
          return;
        }
        if (!isMetricAccordionOpen()) {
          stockMetricStatusEl.textContent = "Expand Metric Percentile Panel to load percentile history.";
          return;
        }
        if (stockMetricLoadedSymbol === currentSymbol || stockMetricLoadingSymbol === currentSymbol) {
          return;
        }
        stockMetricStatusEl.textContent = "Loading metric percentile panel...";
        stockMetricLoadingSymbol = currentSymbol;
        void loadStockMetricPanel(currentSymbol);
      }

      async function analyzeSingleStock(refresh = false) {
        const code = stockCodeInput.value.trim();
        if (!/^\d{6}$/.test(code)) {
          singleStatusEl.textContent = "Please input a valid 6-digit stock code.";
          return;
        }

        analyzeBtn.disabled = true;
        refreshSingleStockBtn.disabled = true;
        singleStatusEl.textContent = refresh
          ? "Refreshing upstream stock data..."
          : "Loading cached stock snapshot...";
        stockMetricStatusEl.textContent = "";
        realtimeStatusEl.textContent = "";

        try {
          const res = await fetch(`${apiBase}/api/analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stock_code: code, refresh }),
          });
          const data = await parseJsonResponse(res);
          if (!res.ok) throw new Error(data.detail || "Request failed");

          currentPriceRows = data.price_data || [];
          currentFinancialRows = data.financial_summary || [];
          currentSymbol = data.symbol || code;
          currentSymbolName = data.symbol_name || data.realtime?.name || null;
          stockMetricLoadedSymbol = null;
          stockMetricLoadingSymbol = null;
          reportCodeInput.value = currentSymbol;
          renderPriceRows(currentPriceRows);
          renderFinancialRows(currentFinancialRows);
          updateMetrics(data.symbol, currentPriceRows, currentFinancialRows);
          metricSymbol.textContent = currentSymbolName ? `${currentSymbol} ${currentSymbolName}` : currentSymbol;

          const warningText = summarizeWarnings(data.warnings || []);
          singleStatusEl.textContent = `${
            refresh ? "Refreshed" : "Loaded cached snapshot for"
          } ${data.symbol}. Price rows: ${currentPriceRows.length}, Financial rows: ${currentFinancialRows.length}.${warningText}`;

          if (currentSymbol) {
            stockMetricTableBody.innerHTML = "";
            maybeLoadMetricPanel();
            realtimeStatusEl.textContent = refresh
              ? "Realtime quote will update on the next background refresh."
              : "Using historical latest close until background realtime refresh.";
            if (latestRealtimeSnapshotData) {
              applyCachedSingleRealtimeSnapshot();
            }
          }
        } catch (err) {
          if (isBackendUnreachable(err)) {
            singleStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
          } else {
            singleStatusEl.textContent = `Error: ${err.message}`;
          }
          currentPriceRows = [];
          currentFinancialRows = [];
          currentSymbol = null;
          currentSymbolName = null;
          priceTableBody.innerHTML = "";
          financialTableBody.innerHTML = "";
          stockMetricTableBody.innerHTML = "";
          stockMetricStatusEl.textContent = "";
          realtimeStatusEl.textContent = "";
          priceMetaEl.textContent = "";
          resetMetrics();
        } finally {
          analyzeBtn.disabled = false;
          refreshSingleStockBtn.disabled = false;
        }
      }

      async function loadStockMetricPanel(symbol) {
        try {
          const { response, data: metricData } = await fetchJsonWithTimeout(
            `${apiBase}/stock_metrics?symbol=${encodeURIComponent(symbol)}`,
            {},
            5000,
            "Metrics endpoint"
          );
          if (!response.ok) throw new Error(metricData.detail || "Metric request failed");
          if (symbol !== currentSymbol) return;
          renderStockMetricRows(metricData.metrics || []);
          stockMetricLoadedSymbol = symbol;
          if (metricData.valuation_refresh_in_flight || metricData.financial_refresh_in_flight) {
            stockMetricStatusEl.textContent = metricData.as_of
              ? `As of: ${metricData.as_of}. Metric history refreshing in background.`
              : "Metric panel warming in background; history not ready yet.";
          } else {
            stockMetricStatusEl.textContent = metricData.as_of
              ? `As of: ${metricData.as_of}.`
              : "As of: -";
          }
        } catch (err) {
          if (symbol !== currentSymbol) return;
          stockMetricLoadedSymbol = null;
          stockMetricTableBody.innerHTML = "";
          stockMetricStatusEl.textContent = isBackendUnreachable(err)
            ? `Error: Cannot connect to backend at ${apiBase}.`
            : `Metric panel unavailable: ${err.message}`;
        } finally {
          if (symbol === currentSymbol) {
            stockMetricLoadingSymbol = null;
          }
        }
      }

      function applySingleRealtimeSnapshot(data) {
        if (!currentSymbol) return;
        const quote = (data.quotes || {})[currentSymbol];
        if (!quote) {
          realtimeStatusEl.textContent = data.refresh_in_flight
            ? "Realtime refresh in progress; using historical latest close."
            : "Realtime quote unavailable; using historical latest close.";
          return;
        }
        updateSingleRealtimeDisplay(quote);
        if (data.is_stale && data.as_of) {
          realtimeStatusEl.textContent = `Realtime cache as of ${data.as_of}; refresh in progress.`;
        } else if (quote.updated_at) {
          realtimeStatusEl.textContent = `Realtime as of ${quote.updated_at}.`;
        } else if (data.as_of) {
          realtimeStatusEl.textContent = `Realtime cache as of ${data.as_of}.`;
        } else {
          realtimeStatusEl.textContent = "Realtime quote loaded.";
        }
      }

      function applyWatchlistRealtimeSnapshot(data) {
        if (!watchlistSymbols.length) return;
        if (latestWatchlistRealtimeRequestToken !== watchlistRequestToken) return;
        if (!latestWatchlistRealtimeBaseStatus) return;

        const quotes = data.quotes || {};
        applyRealtimeToWatchlist(quotes);
        const quoteCount = watchlistSymbols.filter((symbol) => quotes[symbol]).length;
        watchlistStatusEl.textContent =
          quoteCount > 0
            ? data.is_stale && data.as_of
              ? `${latestWatchlistRealtimeBaseStatus} Realtime cache as of ${data.as_of}; refresh in progress.`
              : `${latestWatchlistRealtimeBaseStatus} Realtime loaded for ${quoteCount} symbol${quoteCount === 1 ? "" : "s"}.`
            : data.refresh_in_flight
              ? `${latestWatchlistRealtimeBaseStatus} Realtime refresh in progress; showing cached watchlist snapshot.`
              : `${latestWatchlistRealtimeBaseStatus} Realtime quote unavailable; showing cached watchlist snapshot.`;
      }

      function applyRealtimeSnapshotFailure() {
        if (currentSymbol) {
          realtimeStatusEl.textContent = "Realtime quote unavailable; using historical latest close.";
        }
        if (
          watchlistSymbols.length &&
          latestWatchlistRealtimeRequestToken === watchlistRequestToken &&
          latestWatchlistRealtimeBaseStatus
        ) {
          watchlistStatusEl.textContent = `${latestWatchlistRealtimeBaseStatus} Realtime quote unavailable; showing cached watchlist snapshot.`;
        }
      }

      function applyCachedSingleRealtimeSnapshot() {
        if (!currentSymbol || !latestRealtimeSnapshotData) return false;
        const quote = (latestRealtimeSnapshotData.quotes || {})[currentSymbol];
        if (!quote) return false;
        applySingleRealtimeSnapshot(latestRealtimeSnapshotData);
        return true;
      }

      function applyCachedWatchlistRealtimeSnapshot() {
        if (!watchlistSymbols.length || !latestRealtimeSnapshotData) return false;
        const quotes = latestRealtimeSnapshotData.quotes || {};
        const hasAnyQuote = watchlistSymbols.some((symbol) => Boolean(quotes[symbol]));
        if (!hasAnyQuote) return false;
        applyWatchlistRealtimeSnapshot(latestRealtimeSnapshotData);
        return true;
      }

      async function requestSharedRealtimeSnapshot(symbols) {
        symbols.filter(Boolean).forEach((symbol) => {
          if (!inFlightRealtimeSymbols.has(symbol)) {
            queuedRealtimeSymbols.add(symbol);
          }
        });

        if (!queuedRealtimeSymbols.size && realtimeRequestPromise) return realtimeRequestPromise;
        if (realtimeRequestPromise) return realtimeRequestPromise;

        const requestedSymbols = [...queuedRealtimeSymbols];
        if (!requestedSymbols.length) return null;
        queuedRealtimeSymbols.clear();
        inFlightRealtimeSymbols = new Set(requestedSymbols);

        realtimeRequestPromise = (async () => {
          try {
            const url = `${apiBase}/api/realtime-prices?symbols=${encodeURIComponent(requestedSymbols.join(","))}`;
            const { response, data } = await fetchJsonWithTimeout(url, {}, 4000, "Realtime endpoint");
            if (!response.ok) throw new Error(data.detail || "Realtime request failed");
            latestRealtimeSnapshotData = data;
            applySingleRealtimeSnapshot(data);
            applyWatchlistRealtimeSnapshot(data);
            return data;
          } catch (err) {
            applyRealtimeSnapshotFailure();
            throw err;
          } finally {
            realtimeRequestPromise = null;
            inFlightRealtimeSymbols = new Set();
            if (queuedRealtimeSymbols.size) {
              void requestSharedRealtimeSnapshot([...queuedRealtimeSymbols]);
            }
          }
        })();

        return realtimeRequestPromise;
      }

      async function loadSingleStockRealtime() {
        if (!currentSymbol) return;
        try {
          await requestSharedRealtimeSnapshot([currentSymbol]);
        } catch (_err) {}
      }

      async function loadWatchlistRealtime(symbols, baseStatusText, requestToken) {
        latestWatchlistRealtimeBaseStatus = baseStatusText;
        latestWatchlistRealtimeRequestToken = requestToken;
        if (!symbols.length) return;
        try {
          await requestSharedRealtimeSnapshot(symbols);
        } catch (_err) {}
      }

      async function loadWatchlistNames(symbols, requestToken) {
        if (!symbols.length) return;
        try {
          const { response, data } = await fetchJsonWithTimeout(
            `${apiBase}/api/stock-names?symbols=${encodeURIComponent(symbols.join(","))}`,
            {},
            3000,
            "Stock names endpoint"
          );
          if (requestToken !== watchlistRequestToken) return;
          if (!response.ok) throw new Error(data.detail || "Stock names request failed");
          const names = data.names || {};
          Object.entries(names).forEach(([symbol, name]) => {
            if (!name) return;
            const row = watchlistTableBody.querySelector(`tr[data-symbol="${symbol}"]`);
            if (!row) return;
            const nameCell = row.querySelector(".watchlist-name");
            if (!nameCell) return;
            if (!nameCell.textContent || nameCell.textContent.trim() === "-") {
              nameCell.textContent = name;
            }
          });
        } catch (_err) {}
      }

      function parseWatchlistInput(text) {
        const raw = text
          .split(/[\n,，\s]+/g)
          .map((x) => x.trim())
          .filter(Boolean);

        const uniq = [];
        raw.forEach((code) => {
          if (!uniq.includes(code)) uniq.push(code);
        });
        return uniq;
      }

      function classifyWarningMessage(message) {
        const text = String(message || "");
        const lower = text.toLowerCase();
        if (lower.includes("price fetch failed") && lower.includes("returned cached data")) {
          return "Price data: cached fallback";
        }
        if (lower.includes("price fetch failed") && lower.includes("no cache available")) {
          return "Price data: unavailable";
        }
        if (lower.includes("financial fetch failed") && lower.includes("returned cached data")) {
          return "Financial data: cached fallback";
        }
        if (lower.includes("financial fetch failed") && lower.includes("no cache available")) {
          return "Financial data: unavailable";
        }
        if (lower.includes("stock name fetch failed")) {
          return "Stock name: unavailable";
        }
        if (lower.includes("realtime quote fetch failed")) {
          return "Realtime quote: historical close used";
        }
        return text;
      }

      function summarizeWarnings(warnings) {
        const summarized = [...new Set((warnings || []).map(classifyWarningMessage).filter(Boolean))];
        return summarized.length ? ` Warnings: ${summarized.join(" | ")}` : "";
      }

      function buildWatchlistStatusDetail(item) {
        if (item.error) {
          return `Error: ${item.error}`;
        }
        const warningDetails = [...new Set((item.warnings || []).map(classifyWarningMessage).filter(Boolean))];
        return warningDetails.join("\n");
      }

      function watchlistStatusBadge(item) {
        const detail = buildWatchlistStatusDetail(item);
        const tooltip = escapeHtmlAttribute(detail);
        if (item.error) {
          return `<span class="status bad has-detail" title="${tooltip}" aria-label="${tooltip}" tabindex="0">Error</span>`;
        }
        if ((item.warnings || []).length) {
          return `<span class="status warn has-detail" title="${tooltip}" aria-label="${tooltip}" tabindex="0">Warning</span>`;
        }
        return `<span class="status ok">OK</span>`;
      }

      function renderWatchlistRows(rows) {
        watchlistTableBody.innerHTML = "";
        watchlistSymbols = [];
        rows.forEach((item) => {
          const p = item.latest_price || {};
          const f = item.latest_financial || {};
          const nameText = item.symbol_name || item.realtime?.name || "-";
          const closePercentileText =
            item.close_percentile === null || item.close_percentile === undefined
              ? "-"
              : `${item.close_percentile}%`;
          const tr = document.createElement("tr");
          tr.setAttribute("data-symbol", item.symbol ?? "");
          tr.innerHTML = `
            <td>${item.symbol ?? "-"}</td>
            <td class="watchlist-name">${nameText}</td>
            <td class="watchlist-time">${p.trade_date ?? "-"}</td>
            <td class="watchlist-close">${formatNumber(p.close)}</td>
            <td>${closePercentileText}</td>
            <td>${formatNumber(f.revenue)}</td>
            <td>${formatNumber(f.net_profit)}</td>
            <td>${formatNumber(f.roe)}</td>
            <td>${formatNumber(f.debt_ratio)}</td>
            <td>${watchlistStatusBadge(item)}</td>
          `;
          watchlistTableBody.appendChild(tr);
          if (item.symbol && !item.error) {
            watchlistSymbols.push(item.symbol);
          }
        });
      }

      function applyRealtimeToWatchlist(quotes) {
        Object.entries(quotes || {}).forEach(([symbol, quote]) => {
          const row = watchlistTableBody.querySelector(`tr[data-symbol="${symbol}"]`);
          if (!row) return;
          const closeCell = row.querySelector(".watchlist-close");
          const timeCell = row.querySelector(".watchlist-time");
          const nameCell = row.querySelector(".watchlist-name");
          if (closeCell && quote.latest_price !== null && quote.latest_price !== undefined) {
            closeCell.textContent = formatNumber(quote.latest_price);
          }
          if (timeCell && quote.updated_at) {
            timeCell.textContent = String(quote.updated_at);
          }
          if (nameCell && quote.name) {
            nameCell.textContent = quote.name;
          }
        });
      }

      function watchlistSymbolsMissingNames(symbols) {
        return symbols.filter((symbol) => {
          const row = watchlistTableBody.querySelector(`tr[data-symbol="${symbol}"]`);
          const nameCell = row?.querySelector(".watchlist-name");
          const nameText = nameCell?.textContent?.trim() || "";
          return !nameText || nameText === "-";
        });
      }

      async function refreshRealtimePrices() {
        if (document.visibilityState !== "visible") return;
        if (realtimeRefreshInFlight) return;
        const symbolPool = [];
        if (currentSymbol) symbolPool.push(currentSymbol);
        watchlistSymbols.forEach((symbol) => {
          if (!symbolPool.includes(symbol)) symbolPool.push(symbol);
        });
        if (!symbolPool.length) return;

        realtimeRefreshInFlight = true;
        try {
          await requestSharedRealtimeSnapshot(symbolPool);
        } catch (_err) {
          // Silent fail: realtime feed should not block base analysis UX.
        } finally {
          realtimeRefreshInFlight = false;
        }
      }

      async function analyzeWatchlist(refresh = false) {
        const codes = parseWatchlistInput(watchlistCodes.value);
        if (!codes.length) {
          watchlistStatusEl.textContent = "Please input at least one stock code.";
          return;
        }

        analyzeWatchlistBtn.disabled = true;
        refreshWatchlistBtn.disabled = true;
        const requestToken = ++watchlistRequestToken;
        watchlistStatusEl.textContent = refresh
          ? `Refreshing ${codes.length} symbols...`
          : `Loading cached watchlist for ${codes.length} symbols...`;
        watchlistTableBody.innerHTML = "";
        watchlistSymbols = [];

        try {
          const res = await fetch(`${apiBase}/api/analyze-multi`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stock_codes: codes, refresh }),
          });
          const data = await parseJsonResponse(res);
          if (!res.ok) throw new Error(data.detail || "Request failed");

          const rows = data.results || [];
          renderWatchlistRows(rows);
          const okCount = rows.filter((x) => !x.error).length;
          const baseStatusText = `${
            refresh ? "Refreshed" : "Loaded cached watchlist."
          } ${okCount}/${rows.length} symbols succeeded.`;
          latestWatchlistRealtimeBaseStatus = baseStatusText;
          latestWatchlistRealtimeRequestToken = requestToken;
          watchlistStatusEl.textContent = watchlistSymbols.length
            ? refresh
              ? `${baseStatusText} Realtime will update on the next background refresh.`
              : `${baseStatusText} Using cached watchlist snapshot until background realtime refresh.`
            : baseStatusText;
          if (latestRealtimeSnapshotData) {
            applyCachedWatchlistRealtimeSnapshot();
          }
          const unresolvedNameSymbols = watchlistSymbolsMissingNames(watchlistSymbols);
          if (unresolvedNameSymbols.length) {
            void loadWatchlistNames(unresolvedNameSymbols, requestToken);
          }
        } catch (err) {
          watchlistTableBody.innerHTML = "";
          watchlistSymbols = [];
          if (isBackendUnreachable(err)) {
            watchlistStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
          } else {
            watchlistStatusEl.textContent = `Error: ${err.message}`;
          }
        } finally {
          analyzeWatchlistBtn.disabled = false;
          refreshWatchlistBtn.disabled = false;
        }
      }

      function clearMacroTable() {
        macroTableHead.innerHTML = "";
        macroTableBody.innerHTML = "";
      }

      function clearMacroSignals() {
        macroSignalTableBody.innerHTML = "";
      }

      function humanizeSourceLabel(source) {
        const normalized = String(source || "").trim();
        const rawKey = normalized.includes(":") ? normalized.split(":", 1)[0] : normalized;
        const labelMap = new Map([
          ["spot_hog_lean_price_soozhu", "搜猪网"],
          ["spot_corn_price_soozhu", "搜猪网"],
          ["moa_market_info", "农业农村部"],
          ["futures_zh_daily_sina", "新浪财经"],
          ["futures_global_hist_em", "东方财富"],
          ["macro_china_construction_price_index", "东方财富"],
          ["futures_spot_price_daily", "100ppi"],
          ["forex_hist_em", "东方财富"],
          ["index_global_hist_em", "东方财富"],
          ["us_treasury_curve", "美国财政部"],
          ["zhaomei_water_coal", "找煤网"],
          ["sxcoal_cci5500", "Sxcoal"],
          ["cempi_index", "水泥网"],
        ]);
        return labelMap.get(rawKey) || normalized || "-";
      }

      function renderIndustryRows(rows) {
        industryTableBody.innerHTML = "";
        rows.forEach((row) => {
          const oneYear = row["1y_percentile"] == null ? "-" : `${row["1y_percentile"]}%`;
          const fiveYear = row["5y_percentile"] == null ? "-" : `${row["5y_percentile"]}%`;
          const source = row.source || humanizeSourceLabel(row.source || "-");
          const linkHtml = row.source_url
            ? `<a href="${escapeHtmlAttribute(row.source_url)}" target="_blank" rel="noreferrer">Open</a>`
            : "-";
          const status = row.status || "-";
          const errorText = row.error || "-";
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${row.industry ?? "-"}</td>
            <td>${row.display_name ?? row.indicator ?? "-"}</td>
            <td>${formatNumber(row.value)}</td>
            <td>${row.as_of ?? "-"}</td>
            <td>${oneYear}</td>
            <td>${fiveYear}</td>
            <td>${source}</td>
            <td>${linkHtml}</td>
            <td>${status}</td>
            <td>${errorText}</td>
          `;
          industryTableBody.appendChild(tr);
        });
      }

      function flattenIndustryGroups(data) {
        const groups = data?.groups;
        if (!Array.isArray(groups) || !groups.length) {
          return Array.isArray(data?.rows) ? data.rows : [];
        }
        const out = [];
        groups.forEach((group) => {
          (group?.rows || []).forEach((row) => out.push(row));
        });
        return out;
      }

      function renderMacroSignals(rows) {
        clearMacroSignals();
        rows.forEach((row) => {
          const extraNote =
            row.indicator === "china_pmi"
              ? `<span class="signal-note" title="china_pmi uses fixed threshold rule: >=50 Expansion, <50 Contraction">Threshold: 50</span>`
              : "";
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${row.indicator ?? "-"}</td>
            <td>${formatNumber(row.value)}</td>
            <td>${row.percentile ?? "-"}%</td>
            <td><span class="badge-signal ${row.signal_color || "yellow"}">${row.signal_label || "-"}</span>${extraNote}</td>
          `;
          macroSignalTableBody.appendChild(tr);
        });
      }

      function renderValuationPanel(rows) {
        valuationPanelEl.innerHTML = "";
        const signalMap = {};
        rows.forEach((row) => {
          signalMap[row.indicator] = row;
        });

        valuationIndicatorConfig.forEach((item) => {
          const signal = signalMap[item.key];
          const card = document.createElement("div");
          card.className = "valuation-item";

          if (!signal) {
            card.innerHTML = `
              <div class="name">${item.label}</div>
              <div class="meta">Value: - | Percentile: -</div>
              <div class="meta"><span class="badge-signal yellow">No Data</span></div>
            `;
            valuationPanelEl.appendChild(card);
            return;
          }

          card.innerHTML = `
            <div class="name">${item.label}</div>
            <div class="meta">Value: ${formatNumber(signal.value)} | Percentile: ${signal.percentile}%</div>
            <div class="meta"><span class="badge-signal ${signal.signal_color || "yellow"}">${signal.signal_label || "-"}</span></div>
          `;
          valuationPanelEl.appendChild(card);
        });
      }

      function fillMissingValues(rows) {
        if (!rows.length) return [];
        const asc = [...rows].reverse();
        const keys = Object.keys(asc[0]).filter((k) => k !== "date");
        const last = {};

        const outAsc = asc.map((row) => {
          const cloned = { ...row };
          keys.forEach((k) => {
            if (cloned[k] === null || cloned[k] === undefined || cloned[k] === "") {
              if (last[k] !== undefined) cloned[k] = last[k];
            } else {
              last[k] = cloned[k];
            }
          });
          return cloned;
        });

        return outAsc.reverse();
      }

      function buildMissingHint(rows) {
        if (!rows.length) return "No data loaded.";
        const keys = Object.keys(rows[0]).filter((k) => k !== "date");
        const parts = keys.map((k) => {
          let nn = 0;
          rows.forEach((r) => {
            if (r[k] !== null && r[k] !== undefined && r[k] !== "") nn += 1;
          });
          return `${k}: ${nn}/${rows.length}`;
        });
        return `Non-null counts in current view: ${parts.join(" | ")}`;
      }

      function renderMacroRows(rows) {
        clearMacroTable();
        if (!rows.length) {
          macroHintEl.textContent = "No rows found in selected table/limit.";
          return;
        }

        const keys = Object.keys(rows[0]).sort((a, b) => {
          if (a === "date") return -1;
          if (b === "date") return 1;
          return 0;
        });

        const headTr = document.createElement("tr");
        keys.forEach((k) => {
          const th = document.createElement("th");
          th.textContent = k;
          headTr.appendChild(th);
        });
        macroTableHead.appendChild(headTr);

        rows.forEach((row) => {
          const tr = document.createElement("tr");
          keys.forEach((k) => {
            const td = document.createElement("td");
            td.textContent = k === "date" ? row[k] ?? "-" : formatNumber(row[k]);
            tr.appendChild(td);
          });
          macroTableBody.appendChild(tr);
        });

        macroHintEl.textContent = buildMissingHint(rows);
      }

      async function loadMacroIndicators() {
        const table = macroTableSelect.value;
        const limit = Math.max(1, Math.min(500, Number(macroLimitInput.value || 30)));
        macroLimitInput.value = String(limit);

        loadMacroBtn.disabled = true;
        macroStatusEl.textContent = "Loading macro indicators...";
        macroHintEl.textContent = "";
        clearMacroTable();

        try {
          const rowsUrl = `${apiBase}/api/macro-indicators?table=${encodeURIComponent(table)}&limit=${limit}`;
          const signalsUrl = `${apiBase}/macro_signals?table=${encodeURIComponent(table)}`;

          const [res, signalRes] = await Promise.all([fetch(rowsUrl), fetch(signalsUrl)]);
          const [data, signalData] = await Promise.all([
            parseJsonResponse(res),
            parseJsonResponse(signalRes, "Macro signals endpoint"),
          ]);
          if (!res.ok) throw new Error(data.detail || "Request failed");
          if (!signalRes.ok) throw new Error(signalData.detail || "Signal request failed");

          lastMacroRows = data.rows || [];
          const viewRows = macroFillMissing.checked ? fillMissingValues(lastMacroRows) : lastMacroRows;
          renderMacroRows(viewRows);
          renderMacroSignals(signalData || []);
          renderValuationPanel(signalData || []);
          const displayName = macroTableLabelMap[table] || table;
          macroStatusEl.textContent = `Loaded ${displayName}. Rows: ${viewRows.length}. Limit: ${limit}.`;
        } catch (err) {
          lastMacroRows = [];
          clearMacroTable();
          clearMacroSignals();
          valuationPanelEl.innerHTML = "";
          if (isBackendUnreachable(err)) {
            macroStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}. Table cleared (not refreshed).`;
          } else {
            macroStatusEl.textContent = `Error: ${err.message}`;
          }
        } finally {
          loadMacroBtn.disabled = false;
        }
      }

      async function loadIndustryCycles() {
        loadIndustryBtn.disabled = true;
        industryStatusEl.textContent = "Loading industry cycles...";

        try {
          const res = await fetch(`${apiBase}/industry_cycles?refresh=true&refresh_external=false`);
          const data = await parseJsonResponse(res);
          if (!res.ok) throw new Error(data.detail || `Request failed (HTTP ${res.status})`);
          const rows = flattenIndustryGroups(data);
          renderIndustryRows(rows);
          const warningText = buildIndustryWarningText(data);
          industryStatusEl.textContent = `Loaded ${rows.length} indicators. As of: ${data.as_of || "-"}. Refreshed at: ${data.refreshed_at || "-"}.${warningText}`;
        } catch (err) {
          if (isBackendUnreachable(err)) {
            industryStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
          } else {
            industryStatusEl.textContent = `Error: ${err.message}`;
          }
        } finally {
          loadIndustryBtn.disabled = false;
        }
      }

      async function loadCachedIndustryCycles() {
        loadIndustryBtn.disabled = true;
        refreshExternalDataBtn.disabled = true;
        industryStatusEl.textContent = "Loading cached industry snapshot...";
        externalDataStatusEl.textContent = "Loading cached external snapshot...";

        try {
          const res = await fetch(`${apiBase}/industry_cycles?refresh=false&refresh_external=false`);
          const data = await parseJsonResponse(res, "Industry cache endpoint");
          if (!res.ok) throw new Error(data.detail || `Request failed (HTTP ${res.status})`);
          const rows = flattenIndustryGroups(data);
          const externalRows = data.external_rows || [];
          renderIndustryRows(rows);
          renderExternalDataReferences(externalRows);
          const warningText = buildIndustryWarningText(data);
          const industryAsOf = data.as_of || "-";
          const externalAsOf = latestAsOfFromRows(externalRows);
          industryStatusEl.textContent = `Showing cached snapshot. Industry as of: ${industryAsOf}. Refreshed at: ${data.refreshed_at || "-"}.${warningText}`;
          externalDataStatusEl.textContent = `Showing cached snapshot. External data as of: ${externalAsOf}.`;
        } catch (err) {
          industryTableBody.innerHTML = "";
          externalDataTableBody.innerHTML = "";
          if (isBackendUnreachable(err)) {
            industryStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
            externalDataStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
          } else {
            industryStatusEl.textContent = `Error: ${err.message}`;
            externalDataStatusEl.textContent = `Error: ${err.message}`;
          }
        } finally {
          loadIndustryBtn.disabled = false;
          refreshExternalDataBtn.disabled = false;
        }
      }

      async function refreshExternalDataReferences() {
        refreshExternalDataBtn.disabled = true;
        externalDataStatusEl.textContent = "Refreshing external data...";
        externalDataTableBody.innerHTML = "";

        try {
          const res = await fetch(`${apiBase}/industry_cycles?refresh=false&refresh_external=true`);
          const data = await parseJsonResponse(res, "Industry external data endpoint");
          if (!res.ok) throw new Error(data.detail || `Request failed (HTTP ${res.status})`);
          renderExternalDataReferences(data.external_rows || []);
          const refreshedCount = (data.external_rows || []).filter((row) => row.value !== null && row.value !== undefined).length;
          const warningText = buildIndustryWarningText(data);
          externalDataStatusEl.textContent = `External data refreshed. Cached values: ${refreshedCount}.${warningText}`;
        } catch (err) {
          externalDataTableBody.innerHTML = "";
          if (isBackendUnreachable(err)) {
            externalDataStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
          } else {
            externalDataStatusEl.textContent = `Error: ${err.message}`;
          }
        } finally {
          refreshExternalDataBtn.disabled = false;
        }
      }

      analyzeBtn.addEventListener("click", () => analyzeSingleStock(false));
      refreshSingleStockBtn.addEventListener("click", () => analyzeSingleStock(true));
      stockCodeInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") analyzeSingleStock(false);
      });
      priceLimitSelect.addEventListener("change", () => renderPriceRows(currentPriceRows));
      document.querySelectorAll("[data-accordion-toggle]").forEach((buttonEl) => {
        buttonEl.addEventListener("click", () => {
          const bodyId = buttonEl.getAttribute("aria-controls");
          const bodyEl = bodyId ? document.getElementById(bodyId) : null;
          const cardEl = buttonEl.closest(".accordion-card");
          if (!bodyEl || !cardEl) return;
          const isExpanded = buttonEl.getAttribute("aria-expanded") === "true";
          buttonEl.setAttribute("aria-expanded", String(!isExpanded));
          bodyEl.hidden = isExpanded;
          cardEl.classList.toggle("is-open", !isExpanded);
          if (bodyId === "metricAccordionBody" && !isExpanded) {
            maybeLoadMetricPanel();
          }
        });
      });

      analyzeWatchlistBtn.addEventListener("click", () => analyzeWatchlist(false));
      refreshWatchlistBtn.addEventListener("click", () => analyzeWatchlist(true));

      loadMacroBtn.addEventListener("click", loadMacroIndicators);
      macroTableSelect.addEventListener("change", loadMacroIndicators);
      macroLimitInput.addEventListener("change", loadMacroIndicators);
      macroFillMissing.addEventListener("change", () => {
        const rows = macroFillMissing.checked ? fillMissingValues(lastMacroRows) : lastMacroRows;
        renderMacroRows(rows);
      });
      loadIndustryBtn.addEventListener("click", loadIndustryCycles);
      refreshExternalDataBtn.addEventListener("click", refreshExternalDataReferences);

      resetMetrics();
      loadMacroIndicators();
      macroLoadedOnce = true;
      // Poll realtime prices every 60 seconds when the page is visible; realtime values are not persisted.
      setInterval(refreshRealtimePrices, 60000);
