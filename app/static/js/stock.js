import {
  apiBase,
  classifyWarningMessage,
  summarizeWarnings,
  formatNumber,
  escapeHtmlAttribute,
  isBackendUnreachable,
  parseJsonResponse,
  fetchJsonWithTimeout,
} from "./core.js";

export function setupStockModule({
  dom: {
    analyzeBtn,
    refreshSingleStockBtn,
    stockCodeInput,
    singleStatusEl,
    realtimeStatusEl,
    metricSymbol,
    metricClose,
    metricChange,
    metricQuality,
    priceLimitSelect,
    priceTableBody,
    priceMetaEl,
    financialTableBody,
    stockMetricTableBody,
    stockMetricStatusEl,
    watchlistCodes,
    analyzeWatchlistBtn,
    refreshWatchlistBtn,
    watchlistStatusEl,
    watchlistTableBody,
    reportCodeInput,
  },
}) {
  const metricAccordionToggleEl = document.querySelector('[aria-controls="metricAccordionBody"]');
  const metricAccordionBodyEl = document.getElementById("metricAccordionBody");

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
    singleStatusEl.textContent = refresh ? "Refreshing upstream stock data..." : "Loading cached stock snapshot...";
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
        realtimeStatusEl.textContent =
          refresh
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
        stockMetricStatusEl.textContent = metricData.as_of ? `As of: ${metricData.as_of}.` : "As of: -";
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
        item.close_percentile === null || item.close_percentile === undefined ? "-" : `${item.close_percentile}%`;
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
      const baseStatusText = `${refresh ? "Refreshed" : "Loaded cached watchlist."} ${okCount}/${rows.length} symbols succeeded.`;
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

  analyzeBtn.addEventListener("click", () => analyzeSingleStock(false));
  refreshSingleStockBtn.addEventListener("click", () => analyzeSingleStock(true));
  stockCodeInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeSingleStock(false);
  });
  priceLimitSelect.addEventListener("change", () => renderPriceRows(currentPriceRows));
  analyzeWatchlistBtn.addEventListener("click", () => analyzeWatchlist(false));
  refreshWatchlistBtn.addEventListener("click", () => analyzeWatchlist(true));

  resetMetrics();
  setInterval(refreshRealtimePrices, 60000);

  return {
    getCurrentSymbol() {
      return currentSymbol;
    },
    maybeLoadMetricPanel,
  };
}
