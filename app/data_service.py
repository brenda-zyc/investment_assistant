from __future__ import annotations

import datetime as dt
from functools import lru_cache
import html
import io
import logging
import math
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import time
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import akshare as ak
import pandas as pd
try:
    import certifi
except Exception:  # pragma: no cover - optional dependency guard
    certifi = None
try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency guard
    PdfReader = None

logger = logging.getLogger(__name__)

_STOCK_NAME_RUNTIME_CACHE: dict[str, str] = {}
_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_METRIC_NUM_RE = re.compile(r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)\s*(亿|万|元|%)?")


def normalize_stock_code(stock_code: str) -> str:
    """Validate and normalize a 6-digit A-share stock code."""
    code = stock_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("Stock code must be a 6-digit A-share code, e.g. 600519")
    return code


def _decode_http_bytes(raw: bytes, content_type: str) -> str:
    """Decode response bytes using header charset and common Chinese fallbacks."""
    charset = ""
    match = re.search(r"charset=([a-zA-Z0-9_\-]+)", content_type or "", flags=re.IGNORECASE)
    if match:
        charset = match.group(1).strip().lower()

    candidates = [charset, "utf-8", "gb18030", "gbk", "big5"]
    seen: set[str] = set()
    for enc in candidates:
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _html_to_text(page_text: str) -> tuple[str, str | None]:
    """Extract plain text and optional title from HTML."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page_text, flags=re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1)).strip() if title_match else None

    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", page_text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip(), title


def _build_verified_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi CA bundle when available."""
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _is_ssl_verify_error(exc: Exception) -> bool:
    """Return whether exception indicates certificate verification failure."""
    return "certificate verify failed" in str(exc).lower()


def _extract_pdf_text(raw: bytes, max_pages: int = 120) -> tuple[str, int]:
    """Extract plain text from a PDF byte stream."""
    pypdf_error: str | None = None
    if PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(raw))
            page_count = len(reader.pages)
            chunks: list[str] = []
            for idx, page in enumerate(reader.pages):
                if idx >= max_pages:
                    break
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                if page_text.strip():
                    chunks.append(page_text)
            text = "\n".join(chunks)
            text = text.replace("\u3000", " ")
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            text = re.sub(r"\n{2,}", "\n", text).strip()
            if len(text) >= 40:
                return text, page_count
            pypdf_error = "pypdf extracted too little text"
        except Exception as exc:
            pypdf_error = str(exc)

    textutil_path = shutil.which("textutil")
    if textutil_path:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp_pdf:
                tmp_pdf.write(raw)
                tmp_pdf.flush()
                proc = subprocess.run(
                    [textutil_path, "-convert", "txt", "-stdout", tmp_pdf.name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "textutil conversion failed")

            text = proc.stdout.replace("\u3000", " ")
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            text = re.sub(r"\n{2,}", "\n", text).strip()
            if len(text) < 40:
                raise RuntimeError("textutil extracted too little text")

            page_count = max(1, text.count("\f") + 1)
            return text, page_count
        except Exception as exc:
            fallback_error = str(exc)
        else:
            fallback_error = None
    else:
        fallback_error = "textutil not found"

    detail_parts = []
    if pypdf_error:
        detail_parts.append(f"pypdf: {pypdf_error}")
    if fallback_error:
        detail_parts.append(f"textutil: {fallback_error}")
    detail = "; ".join(detail_parts) if detail_parts else "no available parser"
    raise RuntimeError(
        "Failed to parse PDF text. The PDF may be scanned images; OCR is not supported yet. "
        f"Details: {detail}"
    )


def _parse_mb_env(name: str, default_mb: int) -> int:
    """Read integer MB env var safely."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default_mb
    try:
        value = int(raw)
    except ValueError:
        return default_mb
    return max(1, value)


def fetch_report_text_from_url(
    url: str,
    timeout_sec: int = 12,
    max_bytes: int = 2_500_000,
    pdf_max_bytes: int = 60_000_000,
) -> dict[str, Any]:
    """Fetch report page text from URL, with basic safety guards."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be a valid http(s) address.")
    path_is_pdf = parsed.path.lower().endswith(".pdf")

    pdf_limit_bytes = _parse_mb_env("REPORT_PDF_MAX_MB", default_mb=max(1, pdf_max_bytes // 1_000_000)) * 1_000_000
    html_limit_bytes = _parse_mb_env("REPORT_HTML_MAX_MB", default_mb=max(1, max_bytes // 1_000_000)) * 1_000_000

    req = Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
    insecure_ssl_used = False
    try:
        ssl_context = _build_verified_ssl_context()
        with urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:  # nosec B310 - validated scheme and controlled usage
            content_type = str(resp.headers.get("Content-Type", "")).lower()
            is_pdf = "application/pdf" in content_type or path_is_pdf
            effective_max = pdf_limit_bytes if is_pdf else html_limit_bytes
            content_length_text = str(resp.headers.get("Content-Length") or "").strip()
            if content_length_text.isdigit() and int(content_length_text) > effective_max:
                if is_pdf:
                    raise RuntimeError(
                        f"PDF file is too large ({int(content_length_text) / 1_000_000:.1f}MB). "
                        f"Current limit is {effective_max / 1_000_000:.0f}MB."
                    )
                raise RuntimeError("Report page is too large to parse. Please provide a smaller page link.")
            raw = resp.read(effective_max + 1)
    except Exception as exc:
        # Env escape hatch for machines with broken local certificate stores.
        allow_insecure_ssl = os.getenv("REPORT_URL_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes"}
        if _is_ssl_verify_error(exc) and allow_insecure_ssl:
            insecure_ssl_used = True
            insecure_context = ssl._create_unverified_context()
            with urlopen(req, timeout=timeout_sec, context=insecure_context) as resp:  # nosec B310
                content_type = str(resp.headers.get("Content-Type", "")).lower()
                is_pdf = "application/pdf" in content_type or path_is_pdf
                effective_max = pdf_limit_bytes if is_pdf else html_limit_bytes
                raw = resp.read(effective_max + 1)
        elif _is_ssl_verify_error(exc):
            raise RuntimeError(
                "TLS certificate verification failed. "
                "Please refresh local root certificates; if this is a trusted internal environment, "
                "you can temporarily set REPORT_URL_INSECURE_SSL=1 and restart the server."
            ) from exc
        else:
            raise

    is_pdf = "application/pdf" in content_type or path_is_pdf
    effective_max = pdf_limit_bytes if is_pdf else html_limit_bytes
    if len(raw) > effective_max:
        if is_pdf:
            raise RuntimeError(
                f"PDF file is too large to parse. Current limit is {effective_max / 1_000_000:.0f}MB. "
                "Set REPORT_PDF_MAX_MB to increase if needed."
            )
        raise RuntimeError("Report page is too large to parse. Please provide a smaller page link.")
    if is_pdf:
        pdf_text, page_count = _extract_pdf_text(raw)
        file_name = parsed.path.rsplit("/", 1)[-1] or "report.pdf"
        return {
            "url": url,
            "content_type": content_type or "application/pdf",
            "title": file_name,
            "text": pdf_text,
            "pdf_pages": page_count,
            "tls_insecure": insecure_ssl_used,
        }

    decoded = _decode_http_bytes(raw, content_type)
    text, title = _html_to_text(decoded)
    if len(text) < 40:
        raise RuntimeError("Could not extract enough readable text from the URL.")

    return {"url": url, "content_type": content_type, "title": title, "text": text, "tls_insecure": insecure_ssl_used}


def _to_numeric_value(number_text: str, unit: str) -> float | None:
    """Convert numeric text with Chinese unit into normalized float."""
    cleaned = number_text.replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if unit == "亿":
        return value * 100000000.0
    if unit == "万":
        return value * 10000.0
    return value


def _best_metric_match(
    text: str,
    keywords: list[str],
    metric_name: str,
    require_percent: bool = False,
    prefer_large_amount: bool = False,
) -> tuple[float | None, dict[str, Any] | None]:
    """Find best nearby numeric value around a metric keyword."""
    best: tuple[float, float, dict[str, Any]] | None = None

    for keyword in keywords:
        for key_match in re.finditer(re.escape(keyword), text, flags=re.IGNORECASE):
            kw_start = key_match.start()
            snippet_start = max(0, kw_start - 20)
            snippet_end = min(len(text), kw_start + 120)
            snippet = text[snippet_start:snippet_end]
            for num_match in _METRIC_NUM_RE.finditer(snippet):
                number_text = num_match.group(1)
                unit = num_match.group(2) or ""
                value = _to_numeric_value(number_text, unit)
                if value is None:
                    continue

                # Data cleaning rule: skip likely year values (e.g. 2024) without units.
                if unit == "" and 1900 <= value <= 2100:
                    continue
                if metric_name in {"revenue", "net_profit"} and unit == "%":
                    continue
                if require_percent and unit != "%":
                    continue

                distance = abs((snippet_start + num_match.start()) - kw_start)
                score = 120 - distance
                if unit:
                    score += 12
                if require_percent and unit == "%":
                    score += 20
                if prefer_large_amount and unit in {"亿", "万"}:
                    score += 18
                if prefer_large_amount and unit == "" and abs(value) < 1000:
                    score -= 15

                evidence = {
                    "metric": metric_name,
                    "keyword": keyword,
                    "raw_number": f"{number_text}{unit}",
                    "snippet": snippet.strip()[:180],
                }
                candidate = (score, value, evidence)
                if best is None or candidate[0] > best[0]:
                    best = candidate

    if best is None:
        return None, None
    return best[1], best[2]


def extract_financial_row_from_report_text(text: str, title: str | None = None) -> dict[str, Any]:
    """Extract annual financial metrics from Chinese report-like text."""
    body = (title or "") + "\n" + (text or "")
    body = re.sub(r"\s+", " ", body)

    year_candidates = [int(item) for item in re.findall(r"(20\d{2})\s*年", body)]
    date_match = re.search(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?", body)

    report_year = max(year_candidates) if year_candidates else None
    report_date: str | None = None
    if date_match:
        year = int(date_match.group(1))
        month = int(date_match.group(2))
        day = int(date_match.group(3))
        report_year = report_year or year
        try:
            report_date = dt.date(year, month, day).isoformat()
        except ValueError:
            report_date = None
    elif report_year is not None:
        report_date = f"{report_year}-12-31"

    revenue, revenue_evidence = _best_metric_match(
        body,
        keywords=["营业总收入", "营业收入", "主营业务收入"],
        metric_name="revenue",
        prefer_large_amount=True,
    )
    net_profit, net_profit_evidence = _best_metric_match(
        body,
        keywords=["归属于上市公司股东的净利润", "归母净利润", "净利润"],
        metric_name="net_profit",
        prefer_large_amount=True,
    )
    roe, roe_evidence = _best_metric_match(
        body,
        keywords=["净资产收益率", "ROE", "roe"],
        metric_name="roe",
        require_percent=True,
    )
    debt_ratio, debt_evidence = _best_metric_match(
        body,
        keywords=["资产负债率", "负债率"],
        metric_name="debt_ratio",
        require_percent=True,
    )

    evidence = [item for item in [revenue_evidence, net_profit_evidence, roe_evidence, debt_evidence] if item]
    warnings: list[str] = []
    if report_year is None:
        warnings.append("Could not infer report year from text.")
    if revenue is None:
        warnings.append("Revenue was not reliably extracted.")
    if net_profit is None:
        warnings.append("Net profit was not reliably extracted.")
    if roe is None:
        warnings.append("ROE was not reliably extracted.")
    if debt_ratio is None:
        warnings.append("Debt ratio was not reliably extracted.")

    return {
        "report_year": report_year,
        "report_date": report_date,
        "revenue": revenue,
        "net_profit": net_profit,
        "roe": roe,
        "debt_ratio": debt_ratio,
        "evidence": evidence,
        "warnings": warnings,
    }


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


@contextmanager
def without_proxy_env():
    """Temporarily clear proxy env vars for flaky proxy environments."""
    backup: dict[str, str | None] = {k: os.environ.get(k) for k in PROXY_ENV_KEYS + ["NO_PROXY", "no_proxy"]}
    try:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _should_retry_without_proxy(exc: Exception) -> bool:
    """Return True when error message indicates proxy-related failure."""
    msg = str(exc).lower()
    return "proxyerror" in msg or "unable to connect to proxy" in msg


def _should_retry_network(exc: Exception) -> bool:
    """Return True when error message suggests transient network instability."""
    msg = str(exc).lower()
    retry_patterns = (
        "connection aborted",
        "remotedisconnected",
        "remote end closed connection without response",
        "max retries exceeded",
        "read timed out",
        "connect timeout",
        "temporarily unavailable",
        "chunkedencodingerror",
    )
    return any(pattern in msg for pattern in retry_patterns)


def _call_with_resilience(func, *args, **kwargs):
    """Call upstream function with retry and proxy-bypass fallback."""
    # API assumption: upstream providers occasionally fail with transient network errors.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - upstream/network variability
            last_exc = exc
            if _should_retry_without_proxy(exc):
                try:
                    with without_proxy_env():
                        return func(*args, **kwargs)
                except Exception as proxy_exc:
                    last_exc = proxy_exc
            if not _should_retry_network(last_exc):
                raise last_exc
            time.sleep(0.8 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def to_float(value: Any) -> float | None:
    """Convert mixed numeric text into float, returning None for invalid values."""
    # Data cleaning rule: treat '--', empty text, and NaN-like values as missing.
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)

    text = str(value).strip()
    if not text or text in {"--", "nan", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_date_str(value: Any) -> str | None:
    """Convert many date-like formats into ISO date string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y/%m"):
        try:
            parsed = dt.datetime.strptime(text[: len(fmt)], fmt)
            if fmt in {"%Y-%m", "%Y/%m"}:
                parsed = parsed.replace(day=1)
            return parsed.date().isoformat()
        except ValueError:
            continue

    try:
        parsed = pd.to_datetime(text)
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
    except Exception:
        return None


def fetch_price_data(stock_code: str) -> list[dict[str, Any]]:
    """Fetch and normalize A-share daily OHLCV price history."""
    df = _call_with_resilience(ak.stock_zh_a_hist, symbol=stock_code, period="daily", adjust="")

    if df is None or df.empty:
        return []

    column_map = {
        "日期": "trade_date",
        "date": "trade_date",
        "开盘": "open",
        "open": "open",
        "收盘": "close",
        "close": "close",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
    }
    normalized_columns: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip()
        if key in column_map:
            normalized_columns[col] = column_map[key]

    result: list[dict[str, Any]] = []
    for _, row in df.rename(columns=normalized_columns).iterrows():
        trade_date = to_date_str(row.get("trade_date"))
        if not trade_date:
            continue
        result.append(
            {
                "trade_date": trade_date,
                "open": to_float(row.get("open")),
                "close": to_float(row.get("close")),
                "high": to_float(row.get("high")),
                "low": to_float(row.get("low")),
                "volume": to_float(row.get("volume")),
                "amount": to_float(row.get("amount")),
            }
        )
    result.sort(key=lambda x: x["trade_date"])
    return result


def _find_col(columns: list[str], candidates: list[str], exclude: list[str] | None = None) -> str | None:
    """Find the first column containing candidate keywords while avoiding exclusions."""
    exclude = exclude or []
    for col in columns:
        col_clean = col.replace(" ", "")
        if any(ex in col_clean for ex in exclude):
            continue
        if any(keyword in col_clean for keyword in candidates):
            return col
    return None


def _extract_financial_rows_report_style(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Handle row-per-report format, e.g. columns include 报告期/日期 + 指标列."""
    cols = [str(c) for c in df.columns]
    date_col = _find_col(cols, ["报告期", "报告日期", "日期", "截止日期"])
    if not date_col:
        return []

    revenue_col = _find_col(cols, ["营业总收入", "营业收入", "主营业务收入"], ["增长"])
    net_profit_col = _find_col(cols, ["净利润", "归母净利润"], ["增长", "率"])
    roe_col = _find_col(cols, ["净资产收益率", "ROE"])
    debt_ratio_col = _find_col(cols, ["资产负债率", "负债率"])

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        date_text = to_date_str(row.get(date_col))
        if not date_text:
            continue
        report_year = int(date_text[:4])
        rows.append(
            {
                "report_year": report_year,
                "report_date": date_text,
                "revenue": to_float(row.get(revenue_col)) if revenue_col else None,
                "net_profit": to_float(row.get(net_profit_col)) if net_profit_col else None,
                "roe": to_float(row.get(roe_col)) if roe_col else None,
                "debt_ratio": to_float(row.get(debt_ratio_col)) if debt_ratio_col else None,
            }
        )
    return rows


def _extract_financial_rows_metric_style(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Handle metric-row format where first column is metric name and the rest are report dates.
    Example:
        指标 | 2024-12-31 | 2023-12-31 | ...
    """
    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    metric_col = "指标" if "指标" in cols else cols[0]
    date_cols = [col for col in cols if col != metric_col and to_date_str(col)]
    if not date_cols:
        return []

    metric_spec = {
        "revenue": {
            "include": ["营业总收入", "营业收入", "主营业务收入"],
            "exclude": ["增长", "同比", "每股", "占比"],
            "prefer": ["营业总收入", "营业收入"],
        },
        "net_profit": {
            "include": ["归母净利润", "净利润"],
            "exclude": ["增长", "同比", "每股", "扣非", "现金流"],
            "prefer": ["归母净利润", "净利润"],
        },
        "roe": {
            "include": ["净资产收益率", "ROE"],
            "exclude": ["增长", "同比"],
            "prefer": ["净资产收益率", "ROE"],
        },
        "debt_ratio": {
            "include": ["资产负债率", "负债率"],
            "exclude": ["增长", "同比"],
            "prefer": ["资产负债率", "负债率"],
        },
    }

    picked_metrics: dict[str, tuple[int, str]] = {}
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if not metric_name:
            continue
        for key, rule in metric_spec.items():
            include = rule["include"]
            exclude = rule["exclude"]
            prefer = rule["prefer"]
            if not any(label in metric_name for label in include):
                continue
            if any(label in metric_name for label in exclude):
                continue

            score = 10
            for idx, preferred_label in enumerate(prefer):
                if preferred_label in metric_name:
                    score = 100 - idx
                    break

            current = picked_metrics.get(key)
            if current is None or score > current[0]:
                picked_metrics[key] = (score, metric_name)

    metric_name_to_key = {name: key for key, (_, name) in picked_metrics.items()}

    values_by_date: dict[str, dict[str, float | None]] = {}
    for col in date_cols:
        date_text = to_date_str(col)
        if date_text:
            values_by_date[date_text] = {}

    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        matched_key = metric_name_to_key.get(metric_name)
        if not matched_key:
            continue

        for col in date_cols:
            date_text = to_date_str(col)
            if not date_text:
                continue
            values_by_date[date_text][matched_key] = to_float(row.get(col))

    rows: list[dict[str, Any]] = []
    for report_date, metrics in values_by_date.items():
        rows.append(
            {
                "report_year": int(report_date[:4]),
                "report_date": report_date,
                "revenue": metrics.get("revenue"),
                "net_profit": metrics.get("net_profit"),
                "roe": metrics.get("roe"),
                "debt_ratio": metrics.get("debt_ratio"),
            }
        )
    return rows


def _deduplicate_by_year(rows: list[dict[str, Any]], years: int = 5) -> list[dict[str, Any]]:
    """Keep the latest record per year, capped by the requested year count."""
    if not rows:
        return []

    by_year: dict[int, dict[str, Any]] = {}
    sorted_rows = sorted(rows, key=lambda r: r.get("report_date", ""), reverse=True)
    for row in sorted_rows:
        year = int(row["report_year"])
        if year not in by_year:
            by_year[year] = row
        if len(by_year) >= years:
            break

    result = [by_year[y] for y in sorted(by_year.keys(), reverse=True)[:years]]
    return result[:years]


def fetch_financial_summary(stock_code: str) -> list[dict[str, Any]]:
    """
    Fetch and normalize recent annual financial metrics.
    Different data sources may return different table shapes, so we try both parsers.
    """
    all_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for fetcher in (
        lambda: ak.stock_financial_abstract(symbol=stock_code),
        lambda: ak.stock_financial_analysis_indicator(symbol=stock_code),
    ):
        try:
            df = _call_with_resilience(fetcher)
            if df is None or df.empty:
                continue

            rows = _extract_financial_rows_report_style(df)
            if not rows:
                rows = _extract_financial_rows_metric_style(df)
            all_rows.extend(rows)
        except Exception as exc:  # pragma: no cover - network/API variations
            errors.append(str(exc))
            continue

    cleaned = _deduplicate_by_year(all_rows, years=5)
    if not cleaned and errors:
        raise RuntimeError("Unable to fetch financial data from upstream API")
    return cleaned


def _find_date_col(df: pd.DataFrame) -> str | None:
    """Locate the most likely date column in an upstream dataframe."""
    cols = [str(c) for c in df.columns]
    return _find_col(cols, ["日期", "date", "报告期", "报告日期", "截止日期", "trade_date"])


def _extract_series_from_row_style(
    df: pd.DataFrame,
    include_keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Extract metric series from row-wise financial tables."""
    exclude_keywords = exclude_keywords or []
    cols = [str(c) for c in df.columns]
    date_col = _find_date_col(df)
    if not date_col:
        return []

    value_col = _find_col(cols, include_keywords, exclude_keywords)
    if not value_col:
        return []

    points: list[tuple[str, float]] = []
    for _, row in df.iterrows():
        date_text = to_date_str(row.get(date_col))
        value = to_float(row.get(value_col))
        if not date_text or value is None:
            continue
        points.append((date_text, value))
    return points


def _extract_series_from_metric_style(
    df: pd.DataFrame,
    include_keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Extract metric series from metric-row / date-column shaped tables."""
    exclude_keywords = exclude_keywords or []
    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    metric_col = "指标" if "指标" in cols else cols[0]
    date_cols = [col for col in cols if col != metric_col and to_date_str(col)]
    if not date_cols:
        return []

    chosen_metric_name: str | None = None
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if not metric_name:
            continue
        if not any(keyword in metric_name for keyword in include_keywords):
            continue
        if any(keyword in metric_name for keyword in exclude_keywords):
            continue
        chosen_metric_name = metric_name
        break

    if not chosen_metric_name:
        return []

    points: list[tuple[str, float]] = []
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col, "")).replace(" ", "")
        if metric_name != chosen_metric_name:
            continue
        for col in date_cols:
            date_text = to_date_str(col)
            value = to_float(row.get(col))
            if not date_text or value is None:
                continue
            points.append((date_text, value))
        break
    return points


def _dedupe_points(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Deduplicate points by date and return ascending date order."""
    bucket: dict[str, float] = {}
    for date_text, value in points:
        bucket[date_text] = value
    return sorted(bucket.items(), key=lambda x: x[0])


def fetch_valuation_series(stock_code: str) -> dict[str, list[tuple[str, float]]]:
    """Fetch PE/PB historical series for percentile calculations."""
    logger.info("stock_metrics endpoint=stock_a_indicator_lg symbol=%s", stock_code)
    df = _call_with_resilience(ak.stock_a_indicator_lg, symbol=stock_code)
    if df is None or df.empty:
        return {"pe_ttm": [], "pb": []}

    cols = [str(c) for c in df.columns]
    date_col = _find_date_col(df)
    # Financial logic: pick raw PE/PB values and avoid percentile columns from providers.
    pe_col = _find_col(cols, ["市盈率", "pe", "PE", "ttm"], ["分位", "百分位"])
    pb_col = _find_col(cols, ["市净率", "pb", "PB"], ["分位", "百分位"])

    pe_points: list[tuple[str, float]] = []
    pb_points: list[tuple[str, float]] = []
    if date_col:
        for _, row in df.iterrows():
            date_text = to_date_str(row.get(date_col))
            if not date_text:
                continue
            if pe_col:
                pe_value = to_float(row.get(pe_col))
                if pe_value is not None:
                    pe_points.append((date_text, pe_value))
            if pb_col:
                pb_value = to_float(row.get(pb_col))
                if pb_value is not None:
                    pb_points.append((date_text, pb_value))

    pe_points = _dedupe_points(pe_points)
    pb_points = _dedupe_points(pb_points)
    logger.info("stock_metrics points symbol=%s pe_ttm=%d pb=%d", stock_code, len(pe_points), len(pb_points))
    return {"pe_ttm": pe_points, "pb": pb_points}


@lru_cache(maxsize=1)
def _get_stock_name_map() -> dict[str, str]:
    """Load and cache A-share stock code-name map."""
    logger.info("stock_name endpoint=stock_info_a_code_name")
    df = _call_with_resilience(ak.stock_info_a_code_name)
    if df is None or df.empty:
        return {}

    cols = [str(c) for c in df.columns]
    code_col = _find_col(cols, ["code", "代码", "证券代码"])
    name_col = _find_col(cols, ["name", "名称", "简称"])
    if not code_col or not name_col:
        return {}

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get(code_col, "")).strip()
        if not raw_code:
            continue
        normalized_code = raw_code.zfill(6)
        if not re.fullmatch(r"\d{6}", normalized_code):
            continue
        name = str(row.get(name_col, "")).strip()
        if name:
            mapping[normalized_code] = name
    logger.info("stock_name loaded=%d", len(mapping))
    return mapping


def fetch_stock_names(stock_codes: list[str]) -> dict[str, str]:
    """Fetch stock names for requested symbols using cached code-name mapping."""
    normalized_codes = [normalize_stock_code(code) for code in stock_codes]
    if not normalized_codes:
        return {}
    name_map = _get_stock_name_map()
    out: dict[str, str] = {}
    unresolved: list[str] = []
    for code in normalized_codes:
        # API assumption: upstream name list can intermittently fail, so runtime cache
        # keeps last-known names without changing database schema.
        resolved = name_map.get(code) or _STOCK_NAME_RUNTIME_CACHE.get(code, "")
        out[code] = resolved
        if resolved:
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved
        else:
            unresolved.append(code)

    # Fallback: query single-symbol profile for unresolved names.
    for code in unresolved:
        resolved = _fetch_stock_name_single(code)
        if resolved:
            out[code] = resolved
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved
    return out


def _fetch_stock_name_single(stock_code: str) -> str:
    """Fetch one stock name from a single-symbol profile endpoint."""
    try:
        logger.info("stock_name endpoint=stock_individual_info_em symbol=%s", stock_code)
        df = _call_with_resilience(lambda: ak.stock_individual_info_em(symbol=stock_code))
    except Exception:
        return ""
    if df is None or df.empty:
        return ""

    cols = [str(c) for c in df.columns]
    key_col = _find_col(cols, ["item", "项目", "指标"])
    value_col = _find_col(cols, ["value", "数值", "内容"])
    if not key_col or not value_col:
        return ""

    for _, row in df.iterrows():
        key_text = str(row.get(key_col, "")).strip()
        if "简称" not in key_text and "名称" not in key_text:
            continue
        value_text = str(row.get(value_col, "")).strip()
        if value_text:
            return value_text
    return ""


def fetch_realtime_quotes(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch realtime quote snapshot for specified A-share symbols."""
    normalized_codes = [normalize_stock_code(code) for code in stock_codes]
    if not normalized_codes:
        return {}

    logger.info("realtime endpoint=stock_zh_a_spot_em symbols=%d", len(normalized_codes))
    df = _call_with_resilience(ak.stock_zh_a_spot_em)
    if df is None or df.empty:
        return {}

    cols = [str(c) for c in df.columns]
    code_col = _find_col(cols, ["代码", "symbol", "证券代码"])
    name_col = _find_col(cols, ["名称", "简称", "name"])
    price_col = _find_col(cols, ["最新价", "现价", "price"])
    change_pct_col = _find_col(cols, ["涨跌幅", "change", "pct"], ["成交", "换手"])
    update_col = _find_col(cols, ["更新时间", "时间", "update"])
    if not code_col:
        return {}

    name_fallback_map = fetch_stock_names(normalized_codes)
    target_set = set(normalized_codes)
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get(code_col, "")).strip()
        code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
        if code not in target_set:
            continue
        row_name = str(row.get(name_col, "")).strip() if name_col else ""
        resolved_name = row_name or name_fallback_map.get(code, "")
        if resolved_name:
            _STOCK_NAME_RUNTIME_CACHE[code] = resolved_name
        out[code] = {
            "symbol": code,
            "name": resolved_name or None,
            "latest_price": to_float(row.get(price_col)) if price_col else None,
            "change_pct": to_float(row.get(change_pct_col)) if change_pct_col else None,
            "updated_at": str(row.get(update_col)).strip() if update_col else None,
        }
    logger.info("realtime points returned=%d", len(out))
    return out


def fetch_financial_metric_series(stock_code: str) -> dict[str, list[tuple[str, float]]]:
    """Fetch ROE/ROIC/Revenue series from financial endpoints."""
    endpoint_fetchers = (
        ("stock_financial_analysis_indicator", lambda: ak.stock_financial_analysis_indicator(symbol=stock_code)),
        ("stock_financial_abstract", lambda: ak.stock_financial_abstract(symbol=stock_code)),
    )

    metric_specs = {
        "roe": (["净资产收益率", "ROE"], ["增长", "同比"]),
        "roic": (["投入资本回报率", "ROIC", "资本回报率"], ["增长", "同比"]),
        "revenue": (["营业总收入", "营业收入", "主营业务收入"], ["增长", "同比", "占比"]),
    }
    out: dict[str, list[tuple[str, float]]] = {key: [] for key in metric_specs}

    for endpoint_name, fetcher in endpoint_fetchers:
        try:
            logger.info("stock_metrics endpoint=%s symbol=%s", endpoint_name, stock_code)
            df = _call_with_resilience(fetcher)
        except Exception as exc:
            logger.warning("stock_metrics endpoint=%s symbol=%s failed=%s", endpoint_name, stock_code, exc)
            continue

        if df is None or df.empty:
            continue

        for metric_name, (include_keywords, exclude_keywords) in metric_specs.items():
            row_points = _extract_series_from_row_style(df, include_keywords, exclude_keywords)
            metric_points = _extract_series_from_metric_style(df, include_keywords, exclude_keywords)
            merged = _dedupe_points(out[metric_name] + row_points + metric_points)
            out[metric_name] = merged

    logger.info(
        "stock_metrics points symbol=%s roe=%d roic=%d revenue=%d",
        stock_code,
        len(out["roe"]),
        len(out["roic"]),
        len(out["revenue"]),
    )
    return out


def build_revenue_cagr_5y_series(revenue_points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Build rolling 5-year revenue CAGR series from raw revenue observations."""
    if not revenue_points:
        return []
    # Data cleaning rule: CAGR requires strictly positive base and current values.
    points = [(pd.to_datetime(d), v) for d, v in revenue_points if v is not None and v > 0]
    points.sort(key=lambda x: x[0])
    out: list[tuple[str, float]] = []

    for idx, (date_now, rev_now) in enumerate(points):
        best_prev_value: float | None = None
        for prev_date, prev_value in points[:idx]:
            year_diff = (date_now - prev_date).days / 365.25
            if year_diff >= 5 and prev_value > 0:
                best_prev_value = prev_value
        if best_prev_value is None:
            continue
        try:
            cagr = math.pow(rev_now / best_prev_value, 1 / 5) - 1
        except (ValueError, ZeroDivisionError):
            continue
        out.append((date_now.date().isoformat(), cagr))

    # TODO: evaluate fiscal-year alignment instead of fixed 365.25-day approximation.
    return _dedupe_points(out)


def get_industry_indicator_specs() -> list[dict[str, str]]:
    """Compatibility wrapper: use industry service as the single source of truth."""
    from app.industry_service import get_industry_indicator_specs as _get_specs

    return _get_specs()


def fetch_industry_price_rows(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    """Compatibility wrapper: delegate industry ingestion to industry service module."""
    from app.industry_service import fetch_industry_price_rows as _fetch_rows

    return _fetch_rows(start_date=start_date, end_date=end_date)
