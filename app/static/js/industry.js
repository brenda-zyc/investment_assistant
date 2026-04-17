export function setupIndustryModule({
  apiBase,
  summarizeWarnings,
  formatNumber,
  escapeHtmlAttribute,
  isBackendUnreachable,
  parseJsonResponse,
  dom: {
    externalDataTableBody,
    externalDataStatusEl,
    loadIndustryBtn,
    refreshExternalDataBtn,
    industryStatusEl,
    industryTableBody,
  },
}) {
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

  loadIndustryBtn.addEventListener("click", loadIndustryCycles);
  refreshExternalDataBtn.addEventListener("click", refreshExternalDataReferences);

  return {
    loadCachedIndustryCycles,
  };
}
