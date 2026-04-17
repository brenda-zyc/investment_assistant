import {
  apiBase,
  summarizeWarnings,
  formatNumber,
  formatPercent,
  escapeHtml,
  escapeHtmlAttribute,
  isBackendUnreachable,
  parseJsonResponse,
} from "./core.js";

export function setupReportModule({
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
}) {
  let reportQaSession = {
    symbol: null,
    reportKey: null,
    history: [],
    sessionSummary: "",
  };
  let reportQaShowOlderTurns = false;
  const llmStorageKey = "investmentAssistantLlmConfigV1";
  const guidedReportQuestions = [
    "今年利润增长主要来自哪里？",
    "经营现金流和净利润匹配吗？",
    "资本开支压力大吗？",
    "管理层最担心哪些风险？",
    "为什么你认为净利润较为真实？",
    "哪些因素会削弱利润可持续性？",
  ];

  function formatReportQaRichText(value) {
    return escapeHtml(value)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function resetFinancialReportPanel() {
    reportMetricYearEl.textContent = "-";
    reportMetricScoreEl.textContent = "-";
    reportMetricRevenueYoyEl.textContent = "-";
    reportMetricProfitYoyEl.textContent = "-";
    reportSnapshotMetaEl.textContent = "";
    reportSnapshotSectionsEl.innerHTML = "";
    reportInsightListEl.innerHTML = "";
    reportAutoreadListEl.innerHTML = "";
    reportLlmAnalysisEl.innerHTML = "";
    reportEvidenceListEl.innerHTML = "";
    reportDetailTableBody.innerHTML = "";
    reportSourceMetaEl.textContent = "";
    renderReportCurrentMode(null);
    renderReportLlmStatus({ llm_enabled: false, llm_used: false });
  }

  function renderFinancialReportSummary(payload) {
    reportMetricYearEl.textContent = payload.latest_report_year ?? "-";
    if (payload.score === null || payload.score === undefined) {
      reportMetricScoreEl.textContent = "-";
    } else {
      reportMetricScoreEl.textContent = `${payload.score} / 100 (${payload.grade || "-"})`;
    }
    reportMetricRevenueYoyEl.textContent = formatPercent(payload.metrics?.revenue_yoy);
    reportMetricProfitYoyEl.textContent = formatPercent(payload.metrics?.net_profit_yoy);
  }

  function formatReportSnapshotValue(item) {
    const valueType = item?.value_type || "amount";
    if (item?.value === null || item?.value === undefined || item?.value === "") return "-";
    if (valueType === "ratio") return formatPercent(item.value);
    if (valueType === "percent_point") return `${formatNumber(item.value)}%`;
    return formatNumber(item.value);
  }

  function renderFinancialReportSnapshot(snapshot) {
    reportSnapshotSectionsEl.innerHTML = "";
    if (!snapshot || !Array.isArray(snapshot.sections) || !snapshot.sections.length) {
      reportSnapshotMetaEl.textContent = "No structured report snapshot available.";
      return;
    }

    reportSnapshotMetaEl.textContent = `Available fields: ${snapshot.available_count ?? 0} / ${snapshot.total_count ?? 0}`;
    snapshot.sections.forEach((section) => {
      const sectionEl = document.createElement("section");
      sectionEl.className = "report-snapshot-section";
      const itemsHtml = (section.items || [])
        .map((item) => {
          const statusClass = item.status === "available" ? "ok" : "warn";
          const statusText = item.status === "available" ? "Extracted" : "Missing";
          return `
            <div class="report-snapshot-item">
              <div class="meta">
                <div class="name">${escapeHtml(item.label || item.key || "-")}</div>
                <span class="status ${statusClass}">${statusText}</span>
              </div>
              <div class="value">${escapeHtml(formatReportSnapshotValue(item))}</div>
            </div>
          `;
        })
        .join("");
      sectionEl.innerHTML = `
        <h4>${escapeHtml(section.title || "-")}</h4>
        <div class="report-snapshot-items">${itemsHtml}</div>
      `;
      reportSnapshotSectionsEl.appendChild(sectionEl);
    });
  }

  function renderFinancialReportHighlights(highlights) {
    reportInsightListEl.innerHTML = "";
    (highlights || []).forEach((item) => {
      const level = item.level || "info";
      const div = document.createElement("div");
      div.className = `report-insight-item ${level}`;
      div.innerHTML = `
        <div class="title">${item.title || "-"}</div>
        <div class="detail">${item.detail || "-"}</div>
      `;
      reportInsightListEl.appendChild(div);
    });
  }

  function renderFinancialReportEvidence(evidence) {
    reportEvidenceListEl.innerHTML = "";
    (evidence || []).forEach((item) => {
      const div = document.createElement("div");
      div.className = "report-insight-item";
      div.innerHTML = `
        <div class="title">${item.metric || "-"}: ${item.raw_number || "-"}</div>
        <div class="detail">keyword=${item.keyword || "-"} | ${item.snippet || "-"}</div>
      `;
      reportEvidenceListEl.appendChild(div);
    });
  }

  function renderFinancialReportTable(rows) {
    reportDetailTableBody.innerHTML = "";
    (rows || []).forEach((row) => {
      const revenue = Number(row.revenue);
      const netProfit = Number(row.net_profit);
      const netMargin =
        Number.isFinite(revenue) && revenue !== 0 && Number.isFinite(netProfit) ? netProfit / revenue : null;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.report_year ?? "-"}</td>
        <td>${row.report_date ?? "-"}</td>
        <td>${formatNumber(row.revenue)}</td>
        <td>${formatNumber(row.net_profit)}</td>
        <td>${formatPercent(netMargin)}</td>
        <td>${formatNumber(row.roe)}</td>
        <td>${formatNumber(row.debt_ratio)}</td>
      `;
      reportDetailTableBody.appendChild(tr);
    });
  }

  function reportLevelBadge(level, verdict) {
    if (level === "ok") {
      return `<span class="status ok">${verdict}</span>`;
    }
    if (level === "warn") {
      return `<span class="status warn">${verdict}</span>`;
    }
    if (level === "risk") {
      return `<span class="status bad">${verdict}</span>`;
    }
    return `<span class="status">${verdict}</span>`;
  }

  function renderFinancialReportAutoreadAnswers(answers) {
    reportAutoreadListEl.innerHTML = "";
    (answers || []).forEach((item) => {
      const div = document.createElement("div");
      div.className = `report-insight-item ${item.level || "info"}`;
      const evidenceItems = (item.evidence || []).map((line) => `<li>${line || "-"}</li>`).join("");
      div.innerHTML = `
        <div class="report-answer-title">
          <div class="title">${item.question || "-"}</div>
          ${reportLevelBadge(item.level || "info", item.verdict || "-")}
        </div>
        <div class="detail">${item.summary || "-"}</div>
        ${evidenceItems ? `<ul class="report-answer-evidence">${evidenceItems}</ul>` : ""}
      `;
      reportAutoreadListEl.appendChild(div);
    });
  }

  function renderReportCurrentMode(mode) {
    const mapping = {
      historical_fallback: { label: "Current mode: historical fallback", level: "warn" },
      report_text_extracted: { label: "Current mode: report text extracted", level: "ok" },
    };
    const current = mapping[mode] || { label: "Current mode: -", level: "" };
    reportCurrentModeEl.innerHTML = `<span class="status ${current.level}">${current.label}</span>`;
  }

  function renderReportLlmStatus(payload) {
    if (payload?.llm_used) {
      const modelText = payload.llm_model ? ` (${payload.llm_model})` : "";
      reportLlmStatusEl.innerHTML = `<span class="status ok">LLM: enabled${modelText}</span>`;
      return;
    }
    if (payload?.llm_enabled) {
      reportLlmStatusEl.innerHTML = `<span class="status warn">LLM: configured, not used</span>`;
      return;
    }
    reportLlmStatusEl.innerHTML = `<span class="status">LLM: off</span>`;
  }

  function renderReportLlmAnalysis(analysis) {
    reportLlmAnalysisEl.innerHTML = "";
    if (!analysis) return;

    if (analysis.summary) {
      const summaryEl = document.createElement("div");
      summaryEl.className = "report-insight-item";
      summaryEl.innerHTML = `
        <div class="title">LLM Summary</div>
        <div class="detail">${escapeHtml(analysis.summary)}</div>
      `;
      reportLlmAnalysisEl.appendChild(summaryEl);
    }

    (analysis.question_notes || []).forEach((item) => {
      const evidenceItems = (item.evidence || []).map((line) => `<li>${escapeHtml(line || "-")}</li>`).join("");
      const noteEl = document.createElement("div");
      noteEl.className = "report-insight-item";
      noteEl.innerHTML = `
        <div class="title">${escapeHtml(item.question_id || "question_note")}</div>
        <div class="detail">${escapeHtml(item.summary || "-")}</div>
        ${evidenceItems ? `<ul class="report-answer-evidence">${evidenceItems}</ul>` : ""}
      `;
      reportLlmAnalysisEl.appendChild(noteEl);
    });
  }

  function reportQaHasActiveSession() {
    return Boolean(reportQaSession.symbol && reportQaSession.reportKey);
  }

  function reportQaConfidenceClass(confidence) {
    const value = String(confidence || "").toLowerCase();
    if (value === "high") return "ok";
    if (value === "medium") return "warn";
    if (value === "low") return "bad";
    return "";
  }

  function renderReportQaGuidedQuestions() {
    reportQaChipListEl.innerHTML = "";
    guidedReportQuestions.forEach((question, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip-button";
      button.textContent = question;
      button.setAttribute("data-report-qa-chip", String(index));
      button.disabled = !reportQaHasActiveSession();
      button.addEventListener("click", () => {
        if (!reportQaHasActiveSession()) return;
        reportQaInputEl.value = question;
        reportQaInputEl.focus();
      });
      reportQaChipListEl.appendChild(button);
    });
  }

  function syncReportQaControls() {
    const enabled = reportQaHasActiveSession();
    reportQaInputEl.disabled = !enabled;
    reportQaAskBtn.disabled = !enabled;
    reportQaChipListEl.querySelectorAll("button").forEach((button) => {
      button.disabled = !enabled;
    });
  }

  function countReportQaPairs(turns) {
    return (turns || []).filter((turn) => turn && turn.role === "user").length;
  }

  function renderReportQaTranscript() {
    reportQaTranscriptEl.innerHTML = "";
    const olderTurns = reportQaSession.history.slice(0, -6);
    const olderPairCount = countReportQaPairs(olderTurns);
    const visibleTurns = reportQaShowOlderTurns ? reportQaSession.history : reportQaSession.history.slice(-6);
    reportQaOlderToggleEl.hidden = olderTurns.length === 0;
    reportQaOlderToggleEl.textContent = reportQaShowOlderTurns
      ? `Hide older Q&A pairs (${olderPairCount})`
      : `Show older Q&A pairs (${olderPairCount})`;

    if (!reportQaSession.history.length) {
      const emptyEl = document.createElement("div");
      emptyEl.className = "report-qa-empty";
      emptyEl.textContent = reportQaHasActiveSession()
        ? "Ask a question or use a guided chip to start the conversation for this report."
        : "Load or auto-read an annual report before asking questions.";
      reportQaTranscriptEl.appendChild(emptyEl);
      return;
    }

    visibleTurns.forEach((turn, index) => {
      const role = turn.role === "assistant" ? "assistant" : turn.role === "system" ? "system" : "user";
      const turnEl = document.createElement("div");
      turnEl.className = `report-qa-turn ${role}`;
      turnEl.setAttribute("data-report-qa-role", role);
      turnEl.setAttribute("data-report-qa-index", String(index));

      const headEl = document.createElement("div");
      headEl.className = "report-qa-turn-head";

      const roleEl = document.createElement("span");
      roleEl.className = "report-qa-role";
      roleEl.textContent = role === "assistant" ? "Assistant" : role === "system" ? "System" : "You";
      headEl.appendChild(roleEl);

      const metaEl = document.createElement("div");
      metaEl.className = "report-qa-turn-meta";

      if (role === "assistant" && turn.mode) {
        const modeBadge = document.createElement("span");
        modeBadge.className = "status";
        modeBadge.textContent = turn.mode;
        metaEl.appendChild(modeBadge);
      }

      if (role === "assistant" && turn.confidence) {
        const confidenceBadge = document.createElement("span");
        const confidenceClass = reportQaConfidenceClass(turn.confidence);
        confidenceBadge.className = confidenceClass ? `status ${confidenceClass}` : "status";
        confidenceBadge.textContent = `Confidence: ${turn.confidence}`;
        metaEl.appendChild(confidenceBadge);
      }

      if (turn.session_reset) {
        const resetBadge = document.createElement("span");
        resetBadge.className = "status warn";
        resetBadge.textContent = "Session reset";
        metaEl.appendChild(resetBadge);
      }

      if (metaEl.childNodes.length) {
        headEl.appendChild(metaEl);
      }

      const bodyEl = document.createElement("div");
      bodyEl.className = "report-qa-turn-body";
      bodyEl.innerHTML = formatReportQaRichText(turn.content || "-");
      turnEl.appendChild(headEl);
      turnEl.appendChild(bodyEl);

      if (role === "assistant" && Array.isArray(turn.evidence) && turn.evidence.length) {
        const evidenceEl = document.createElement("ul");
        evidenceEl.className = "report-qa-turn-evidence";
        turn.evidence.forEach((item) => {
          const li = document.createElement("li");
          li.textContent = typeof item === "string" ? item : item?.snippet || item?.content || JSON.stringify(item);
          evidenceEl.appendChild(li);
        });
        turnEl.appendChild(evidenceEl);
      }

      if (role === "assistant" && Array.isArray(turn.citations) && turn.citations.length) {
        const citationsEl = document.createElement("ul");
        citationsEl.className = "report-qa-turn-citations";
        turn.citations.forEach((item) => {
          const li = document.createElement("li");
          const citationText =
            typeof item === "string" ? item : item?.snippet || item?.text || item?.content || item?.source || "-";
          const citationUrl = typeof item === "object" && item ? item.url || item.source_url || item.href : "";
          if (citationUrl) {
            li.innerHTML = `<a href="${escapeHtmlAttribute(citationUrl)}" target="_blank" rel="noreferrer">${escapeHtml(citationText)}</a>`;
          } else {
            li.textContent = citationText;
          }
          citationsEl.appendChild(li);
        });
        turnEl.appendChild(citationsEl);
      }

      reportQaTranscriptEl.appendChild(turnEl);
    });
  }

  function resetReportQaSession({ symbol = null, reportKey = null, label = "" } = {}) {
    reportQaShowOlderTurns = false;
    reportQaSession = {
      symbol: symbol || null,
      reportKey: reportKey || null,
      history: [],
      sessionSummary: "",
    };
    reportQaInputEl.value = "";
    reportQaSessionLabelEl.textContent =
      label ||
      (reportQaHasActiveSession()
        ? "Started a new Q&A session for the active report."
        : "Load or auto-read an annual report before asking questions.");
    syncReportQaControls();
    renderReportQaTranscript();
  }

  function appendReportQaTurn(role, content, payload = {}) {
    reportQaSession.history.push({
      role,
      content,
      evidence: Array.isArray(payload.evidence) ? payload.evidence : [],
      citations: Array.isArray(payload.citations) ? payload.citations : [],
      confidence: payload.confidence || "",
      mode: payload.mode || "",
      session_reset: Boolean(payload.session_reset),
    });
    renderReportQaTranscript();
  }

  function readLlmFormConfig() {
    return {
      provider: (llmProviderInput.value || "deepseek").trim(),
      base_url: llmBaseUrlInput.value.trim(),
      model: llmModelInput.value.trim(),
      api_key: llmApiKeyInput.value.trim(),
    };
  }

  function writeLlmFormConfig(config) {
    const data = config || {};
    llmProviderInput.value = data.provider || "deepseek";
    llmBaseUrlInput.value = data.base_url || "https://api.deepseek.com/v1";
    llmModelInput.value = data.model || "deepseek-chat";
    llmApiKeyInput.value = data.api_key || "";
  }

  function persistLlmConfigToLocalStorage() {
    localStorage.setItem(llmStorageKey, JSON.stringify(readLlmFormConfig()));
  }

  function hydrateLlmFormFromLocalStorage() {
    try {
      const raw = localStorage.getItem(llmStorageKey);
      if (!raw) {
        writeLlmFormConfig(null);
        return;
      }
      writeLlmFormConfig(JSON.parse(raw));
    } catch (_err) {
      writeLlmFormConfig(null);
    }
  }

  async function loadLlmSessionStatus() {
    try {
      const res = await fetch(`${apiBase}/api/llm/session-config`);
      const data = await parseJsonResponse(res, "LLM session status endpoint");
      if (!res.ok) throw new Error(data.detail || "Request failed");
      if (data.configured) {
        llmSessionStatusEl.textContent = `Backend session ready: ${data.provider} / ${data.model} / ${data.api_key_masked}.`;
      } else {
        llmSessionStatusEl.textContent = "Backend session not configured yet.";
      }
    } catch (err) {
      if (isBackendUnreachable(err)) {
        llmSessionStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        llmSessionStatusEl.textContent = `Error: ${err.message}`;
      }
    }
  }

  async function saveLlmSessionConfig() {
    persistLlmConfigToLocalStorage();
    saveLlmSessionBtn.disabled = true;
    llmSessionStatusEl.textContent = "Saving LLM session config...";
    try {
      const res = await fetch(`${apiBase}/api/llm/session-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(readLlmFormConfig()),
      });
      const data = await parseJsonResponse(res, "LLM session config endpoint");
      if (!res.ok) throw new Error(data.detail || "Request failed");
      llmSessionStatusEl.textContent = `Backend session ready: ${data.provider} / ${data.model} / ${data.api_key_masked}.`;
    } catch (err) {
      if (isBackendUnreachable(err)) {
        llmSessionStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        llmSessionStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      saveLlmSessionBtn.disabled = false;
    }
  }

  async function testLlmConnection() {
    persistLlmConfigToLocalStorage();
    testLlmConnectionBtn.disabled = true;
    llmSessionStatusEl.textContent = "Testing LLM connection...";
    try {
      const res = await fetch(`${apiBase}/api/llm/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(readLlmFormConfig()),
      });
      const data = await parseJsonResponse(res, "LLM test connection endpoint");
      if (!res.ok) throw new Error(data.detail || "Request failed");
      llmSessionStatusEl.textContent = `LLM connection OK: ${data.provider} / ${data.model}.`;
    } catch (err) {
      if (isBackendUnreachable(err)) {
        llmSessionStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        llmSessionStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      testLlmConnectionBtn.disabled = false;
    }
  }

  async function loadFinancialReport(refresh = false) {
    const code = reportCodeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      reportStatusEl.textContent = "Please input a valid 6-digit stock code.";
      return;
    }

    loadReportBtn.disabled = true;
    refreshReportBtn.disabled = true;
    resetFinancialReportPanel();
    resetReportQaSession({
      symbol: code,
      reportKey: null,
      label: "Load or auto-read an annual report before asking questions.",
    });
    reportStatusEl.textContent = refresh
      ? "Refreshing financial report summary..."
      : "Loading cached financial report summary...";

    try {
      const res = await fetch(
        `${apiBase}/api/financial-report-analysis?symbol=${encodeURIComponent(code)}&refresh=${refresh ? "true" : "false"}`
      );
      const data = await parseJsonResponse(res);
      if (!res.ok) throw new Error(data.detail || "Request failed");

      renderFinancialReportSummary(data);
      renderFinancialReportSnapshot(data.report_snapshot || null);
      renderFinancialReportHighlights(data.highlights || []);
      renderFinancialReportEvidence([]);
      renderFinancialReportTable(data.series || []);
      reportSourceMetaEl.textContent = "";

      const displayName = data.symbol_name ? `${data.symbol} ${data.symbol_name}` : data.symbol;
      const warningText = summarizeWarnings(data.warnings || []);
      reportStatusEl.textContent = `${
        refresh ? "Refreshed" : "Loaded cached summary for"
      } ${displayName}. As of: ${data.as_of || "-"}.${warningText}`;
    } catch (err) {
      resetFinancialReportPanel();
      if (isBackendUnreachable(err)) {
        reportStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        reportStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      loadReportBtn.disabled = false;
      refreshReportBtn.disabled = false;
    }
  }

  async function loadFinancialReportFromUrl(forceRefresh = false) {
    const url = reportUrlInput.value.trim();
    if (!/^https?:\/\//i.test(url)) {
      reportStatusEl.textContent = "Please input a valid http(s) report URL.";
      return;
    }

    const reportSymbol = /^\d{6}$/.test(reportCodeInput.value.trim()) ? reportCodeInput.value.trim() : null;
    analyzeReportUrlBtn.disabled = true;
    resetFinancialReportPanel();
    resetReportQaSession({
      symbol: reportSymbol,
      reportKey: null,
      label: "Load or auto-read an annual report before asking questions.",
    });
    reportStatusEl.textContent = forceRefresh
      ? "Re-fetching and parsing official disclosure report URL..."
      : "Fetching and parsing official disclosure report URL...";

    try {
      const res = await fetch(`${apiBase}/api/financial-report-url-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          reportSymbol ? { url, symbol: reportSymbol, force_refresh: forceRefresh } : { url, force_refresh: forceRefresh }
        ),
      });
      const data = await parseJsonResponse(res);
      if (!res.ok) throw new Error(data.detail || "Request failed");

      const analysis = data.analysis || {};
      renderFinancialReportSummary(analysis);
      renderFinancialReportSnapshot(data.report_snapshot || null);
      renderFinancialReportHighlights(analysis.highlights || []);
      renderFinancialReportEvidence(data.extracted?.evidence || []);
      renderFinancialReportTable(analysis.series || []);

      const sourceTitle = data.source_title ? `Title: ${data.source_title}. ` : "";
      const pageText = data.pdf_pages === null || data.pdf_pages === undefined ? "" : `PDF pages: ${data.pdf_pages}. `;
      const tlsText = data.tls_insecure ? "TLS: insecure fallback enabled. " : "";
      reportSourceMetaEl.textContent = `${sourceTitle}${pageText}${tlsText}Content-Type: ${data.content_type || "-"}.`;
      renderReportCurrentMode(null);
      renderReportLlmStatus({ llm_enabled: false, llm_used: false });
      const reportKey = data.report_key || null;
      const activeSymbol = data.symbol || reportSymbol;
      if (activeSymbol) {
        reportCodeInput.value = activeSymbol;
      }
      resetReportQaSession({
        symbol: activeSymbol,
        reportKey,
        label: reportKey ? "Started a new Q&A session for the active report." : "Load or auto-read an annual report before asking questions.",
      });
      reportStatusEl.textContent = `URL parsed successfully. As of: ${analysis.as_of || "-"}.`;
    } catch (err) {
      resetFinancialReportPanel();
      if (isBackendUnreachable(err)) {
        reportStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        reportStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      analyzeReportUrlBtn.disabled = false;
    }
  }

  async function autoReadAnnualReport(forceRefresh = false) {
    const code = reportCodeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      reportStatusEl.textContent = "Please input a valid 6-digit stock code.";
      return;
    }

    autoReadReportBtn.disabled = true;
    forceReReadReportBtn.disabled = true;
    resetFinancialReportPanel();
    resetReportQaSession({
      symbol: code,
      reportKey: null,
      label: "Load or auto-read an annual report before asking questions.",
    });
    reportStatusEl.textContent = forceRefresh
      ? "Force re-reading the latest annual report..."
      : "Loading persisted or latest annual report...";

    try {
      const res = await fetch(
        `${apiBase}/api/financial-report-autoread?symbol=${encodeURIComponent(code)}&force_refresh=${forceRefresh ? "true" : "false"}`
      );
      const data = await parseJsonResponse(res, "Financial report auto-read endpoint");
      if (!res.ok) throw new Error(data.detail || "Request failed");

      renderFinancialReportAutoreadAnswers(data.answers || []);
      renderFinancialReportSnapshot(data.report_snapshot || null);
      renderReportCurrentMode(data.current_mode || null);
      renderReportLlmStatus(data);
      renderReportLlmAnalysis(data.llm_analysis || null);

      const reportKey = data.report_key || null;
      const reportSymbol = data.symbol || reportCodeInput.value.trim() || null;
      if (reportSymbol) {
        reportCodeInput.value = reportSymbol;
      }
      resetReportQaSession({
        symbol: reportSymbol,
        reportKey,
        label: reportKey
          ? `Q&A Session: ${reportSymbol || data.symbol || "Active report"} / ${data.report?.title || "Active annual report"}`
          : "Load or auto-read an annual report before asking questions.",
      });

      const reportTitle = data.report?.title ? `Title: ${escapeHtmlAttribute(data.report.title)}. ` : "";
      const reportDate = data.report?.published_at ? `Published: ${escapeHtmlAttribute(data.report.published_at)}. ` : "";
      const reportPages =
        data.report?.pdf_pages === null || data.report?.pdf_pages === undefined ? "" : `PDF pages: ${data.report.pdf_pages}. `;
      const reportLink = data.report?.document_url || data.report?.detail_url;
      const reportUrlHtml = reportLink
        ? `Source: <a href="${escapeHtmlAttribute(reportLink)}" target="_blank" rel="noreferrer">Open report</a>.`
        : "";
      const reportMetaHtml = `${reportTitle}${reportDate}${reportPages}${reportUrlHtml}`;
      if (reportMetaHtml.trim()) {
        reportSourceMetaEl.innerHTML = reportMetaHtml;
      } else {
        reportSourceMetaEl.textContent =
          "Report source metadata unavailable. The current three-question output is based on historical financial context fallback.";
      }

      const displayName = data.symbol_name ? `${data.symbol} ${data.symbol_name}` : data.symbol;
      const warningText = summarizeWarnings(data.warnings || []);
      reportStatusEl.textContent = `${
        forceRefresh ? "Force re-read completed for" : "Auto-read completed for"
      } ${displayName}. As of: ${data.as_of || "-"}.${warningText}`;
    } catch (err) {
      if (isBackendUnreachable(err)) {
        reportStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        reportStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      autoReadReportBtn.disabled = false;
      forceReReadReportBtn.disabled = false;
    }
  }

  async function askActiveReport() {
    const question = reportQaInputEl.value.trim();
    if (!question) {
      reportQaSessionLabelEl.textContent = reportQaHasActiveSession()
        ? "Ask a question or use a guided chip to start the conversation for this report."
        : "Load or auto-read an annual report before asking questions.";
      return;
    }
    if (!reportQaHasActiveSession()) {
      reportQaSessionLabelEl.textContent = "Load or auto-read an annual report before asking questions.";
      return;
    }

    const previousHistorySnapshot = reportQaSession.history.map((turn) => ({ ...turn }));
    appendReportQaTurn("user", question);
    reportQaAskBtn.disabled = true;
    reportQaInputEl.disabled = true;

    try {
      const res = await fetch(`${apiBase}/api/financial-report-qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: reportQaSession.symbol,
          report_key: reportQaSession.reportKey,
          question,
          history: reportQaSession.history.slice(-6).map((turn) => ({
            role: turn.role,
            content: turn.content,
            evidence: Array.isArray(turn.evidence) ? turn.evidence : [],
            citations: Array.isArray(turn.citations) ? turn.citations : [],
          })),
          session_summary: reportQaSession.sessionSummary,
          use_llm: true,
        }),
      });
      const data = await parseJsonResponse(res, "Financial report Q&A endpoint");
      if (!res.ok) throw new Error(data.detail || "Request failed");

      reportQaSession.sessionSummary = data.updated_session_summary || reportQaSession.sessionSummary;
      appendReportQaTurn("assistant", data.short_answer || "-", {
        evidence: data.evidence || [],
        citations: data.citations || [],
        confidence: data.confidence || "",
        mode: data.mode || "",
        session_reset: data.session_reset,
      });
      renderReportQaTranscript();
      reportQaInputEl.value = "";
    } catch (err) {
      reportQaSession.history = previousHistorySnapshot;
      renderReportQaTranscript();
      if (isBackendUnreachable(err)) {
        reportStatusEl.textContent = `Error: Cannot connect to backend at ${apiBase}.`;
      } else {
        reportStatusEl.textContent = `Error: ${err.message}`;
      }
    } finally {
      syncReportQaControls();
      reportQaInputEl.focus();
    }
  }

  loadReportBtn.addEventListener("click", () => loadFinancialReport(false));
  refreshReportBtn.addEventListener("click", () => loadFinancialReport(true));
  autoReadReportBtn.addEventListener("click", () => autoReadAnnualReport(false));
  forceReReadReportBtn.addEventListener("click", () => autoReadAnnualReport(true));
  saveLlmSessionBtn.addEventListener("click", saveLlmSessionConfig);
  testLlmConnectionBtn.addEventListener("click", testLlmConnection);
  [llmProviderInput, llmBaseUrlInput, llmModelInput, llmApiKeyInput].forEach((inputEl) => {
    inputEl.addEventListener("input", persistLlmConfigToLocalStorage);
  });
  renderReportQaGuidedQuestions();
  reportQaAskBtn.addEventListener("click", askActiveReport);
  reportQaInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) askActiveReport();
  });
  reportQaOlderToggleEl.addEventListener("click", () => {
    reportQaShowOlderTurns = !reportQaShowOlderTurns;
    renderReportQaTranscript();
  });
  reportCodeInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadFinancialReport(false);
  });
  analyzeReportUrlBtn.addEventListener("click", () => loadFinancialReportFromUrl(false));
  reportUrlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadFinancialReportFromUrl(false);
  });

  hydrateLlmFormFromLocalStorage();
  resetFinancialReportPanel();
  resetReportQaSession({
    symbol: null,
    reportKey: null,
    label: "Load or auto-read an annual report before asking questions.",
  });
  void loadLlmSessionStatus();

  return {
    autoReadAnnualReport,
    loadFinancialReport,
    loadFinancialReportFromUrl,
  };
}
