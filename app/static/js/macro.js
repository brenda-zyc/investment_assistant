export function setupMacroModule({
  apiBase,
  formatNumber,
  isBackendUnreachable,
  parseJsonResponse,
  dom: {
    macroTableSelect,
    macroLimitInput,
    macroFillMissing,
    loadMacroBtn,
    macroStatusEl,
    macroHintEl,
    valuationPanelEl,
    macroSignalTableBody,
    macroTableHead,
    macroTableBody,
  },
}) {
  let lastMacroRows = [];
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

  function clearMacroTable() {
    macroTableHead.innerHTML = "";
    macroTableBody.innerHTML = "";
  }

  function clearMacroSignals() {
    macroSignalTableBody.innerHTML = "";
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

  loadMacroBtn.addEventListener("click", loadMacroIndicators);
  macroTableSelect.addEventListener("change", loadMacroIndicators);
  macroLimitInput.addEventListener("change", loadMacroIndicators);
  macroFillMissing.addEventListener("change", () => {
    const rows = macroFillMissing.checked ? fillMissingValues(lastMacroRows) : lastMacroRows;
    renderMacroRows(rows);
  });

  loadMacroIndicators();

  return {};
}
