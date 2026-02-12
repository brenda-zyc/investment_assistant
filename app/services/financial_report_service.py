from __future__ import annotations

import datetime as dt
import html
import io
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import certifi
except Exception:  # pragma: no cover - optional dependency guard
    certifi = None
try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency guard
    PdfReader = None

_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_METRIC_NUM_RE = re.compile(r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)\s*(亿|万|元|%)?")
_SNIPPET_LEFT_CHARS = 20
_SNIPPET_RIGHT_CHARS = 120


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

    return {
        "url": url,
        "content_type": content_type,
        "title": title,
        "text": text,
        "tls_insecure": insecure_ssl_used,
    }


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


def _get_snippet_window(text: str, keyword_start: int) -> tuple[str, int]:
    """Return local snippet around a keyword plus snippet start offset."""
    snippet_start = max(0, keyword_start - _SNIPPET_LEFT_CHARS)
    snippet_end = min(len(text), keyword_start + _SNIPPET_RIGHT_CHARS)
    return text[snippet_start:snippet_end], snippet_start


def _is_candidate_valid(metric_name: str, unit: str, value: float, require_percent: bool) -> bool:
    """Return whether a numeric candidate is valid for the target metric."""
    # Data cleaning rule: plain 4-digit values are commonly years, not financial metrics.
    if unit == "" and 1900 <= value <= 2100:
        return False
    # Financial logic: revenue/net-profit candidates should not come from percentage values.
    if metric_name in {"revenue", "net_profit"} and unit == "%":
        return False
    if require_percent and unit != "%":
        return False
    return True


def _score_candidate(
    *,
    distance: int,
    unit: str,
    value: float,
    require_percent: bool,
    prefer_large_amount: bool,
) -> float:
    """Score one candidate value near a keyword; higher is better."""
    # Percentile-like ranking principle: score combines proximity + domain-specific priors.
    score = 120 - distance
    if unit:
        score += 12
    if require_percent and unit == "%":
        score += 20
    if prefer_large_amount and unit in {"亿", "万"}:
        score += 18
    if prefer_large_amount and unit == "" and abs(value) < 1000:
        score -= 15
    return score


def _build_candidate_evidence(
    *,
    metric_name: str,
    keyword: str,
    number_text: str,
    unit: str,
    snippet: str,
    distance: int,
    score: float,
    parsed_value: float,
) -> dict[str, Any]:
    """Build evidence payload for explainability and debugging."""
    return {
        "metric": metric_name,
        "keyword": keyword,
        "raw_number": f"{number_text}{unit}",
        "parsed_value": parsed_value,
        "distance": distance,
        "score": score,
        "snippet": snippet.strip()[:180],
    }


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
            snippet, snippet_start = _get_snippet_window(text, kw_start)
            for num_match in _METRIC_NUM_RE.finditer(snippet):
                number_text = num_match.group(1)
                unit = num_match.group(2) or ""
                value = _to_numeric_value(number_text, unit)
                if value is None:
                    continue

                if not _is_candidate_valid(metric_name, unit, value, require_percent):
                    continue

                distance = abs((snippet_start + num_match.start()) - kw_start)
                score = _score_candidate(
                    distance=distance,
                    unit=unit,
                    value=value,
                    require_percent=require_percent,
                    prefer_large_amount=prefer_large_amount,
                )
                evidence = _build_candidate_evidence(
                    metric_name=metric_name,
                    keyword=keyword,
                    number_text=number_text,
                    unit=unit,
                    snippet=snippet,
                    distance=distance,
                    score=score,
                    parsed_value=value,
                )
                candidate = (score, value, evidence)
                if best is None or candidate[0] > best[0]:
                    best = candidate

    # TODO: Expose scoring weights as config for per-industry tuning.
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
