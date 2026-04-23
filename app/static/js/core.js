export const apiBase =
  window.location.protocol === "http:" || window.location.protocol === "https:"
    ? window.location.origin
    : "http://127.0.0.1:8000";

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function formatPercent(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return `${(n * 100).toLocaleString(undefined, { maximumFractionDigits: digits })}%`;
}

export function escapeHtmlAttribute(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function isBackendUnreachable(err) {
  const message = String(err?.message || err || "").toLowerCase();
  return (
    err instanceof TypeError &&
    (message.includes("failed to fetch") || message.includes("networkerror") || message.includes("load failed"))
  );
}

export async function parseJsonResponse(res, errorLabel = "Backend") {
  const bodyText = await res.text();
  try {
    return bodyText ? JSON.parse(bodyText) : {};
  } catch (_err) {
    throw new Error(`${errorLabel} returned non-JSON response (HTTP ${res.status}).`);
  }
}

export async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000, errorLabel = "Backend") {
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

export function classifyWarningMessage(message) {
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

export function summarizeWarnings(warnings) {
  const summarized = [...new Set((warnings || []).map(classifyWarningMessage).filter(Boolean))];
  return summarized.length ? ` Warnings: ${summarized.join(" | ")}` : "";
}
