from __future__ import annotations

import datetime as dt
import html
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlencode, urljoin
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
_CNINFO_STOCK_MAP_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_CNINFO_DISCLOSURE_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_DISCLOSURE_DETAIL_BASE_URL = "http://www.cninfo.com.cn/new/disclosure/detail"
_CNINFO_STATIC_BASE_URL = "http://static.cninfo.com.cn/"
_CNINFO_FULL_YEAR_EXCLUDE_TOKENS = ("摘要", "英文", "取消", "问询", "回复", "更正", "提示性公告")
_PDF_STRUCTURE_MARKERS = ("%pdf-", "endobj", "stream", "endstream", "xref", "trailer", "/type/", "/catalog")


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


def _is_readable_pdf_text(text: str) -> bool:
    """Return whether extracted PDF text looks like readable report content instead of PDF source."""
    cleaned = (text or "").replace("\x00", "").strip()
    if len(cleaned) < 40:
        return False

    head = cleaned[:4000].lower()
    # Data cleaning rule: reject parser outputs that still look like raw PDF objects/streams.
    marker_hits = sum(1 for marker in _PDF_STRUCTURE_MARKERS if marker in head)
    if head.startswith("%pdf-"):
        return False
    if marker_hits >= 4:
        return False
    if re.search(r"\b\d+\s+\d+\s+obj\b", head) and "endobj" in head:
        return False
    return True


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
            if _is_readable_pdf_text(text):
                return text, page_count
            pypdf_error = "pypdf extracted unreadable PDF structure output"
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
            if not _is_readable_pdf_text(text):
                raise RuntimeError("textutil extracted unreadable PDF structure output")

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


def _decode_json_bytes(raw: bytes, content_type: str) -> dict[str, Any]:
    """Decode a JSON response body using the repo's Chinese-safe text decoder."""
    text = _decode_http_bytes(raw, content_type)
    return json.loads(text)


def _build_report_text_body(text: str, title: str | None = None) -> tuple[str, int | None, str | None]:
    """Normalize report text into one searchable body and infer report date metadata."""
    body = (title or "") + "\n" + (text or "")
    body = re.sub(r"\s+", " ", body)

    title_year_match = re.search(r"(20\d{2})\s*年\s*年度报告", str(title or ""))
    year_candidates = [int(item) for item in re.findall(r"(20\d{2})\s*年", body)]
    date_match = re.search(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?", body)

    report_year = int(title_year_match.group(1)) if title_year_match else None
    if report_year is None:
        report_year = max(year_candidates) if year_candidates else None
    report_date: str | None = None
    if title_year_match and report_year is not None:
        # Financial logic: annual-report titles identify the operating year, not the publication date.
        report_date = f"{report_year}-12-31"
    elif date_match:
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

    return body, report_year, report_date


def _load_cninfo_symbol_org_map(timeout_sec: int = 12) -> dict[str, str]:
    """Load CNInfo stock-code to org-id mapping for report disclosure queries."""
    req = Request(_CNINFO_STOCK_MAP_URL, headers={"User-Agent": _HTTP_USER_AGENT})
    with urlopen(req, timeout=timeout_sec) as resp:  # nosec B310 - fixed trusted host for public disclosure data
        payload = _decode_json_bytes(resp.read(), str(resp.headers.get("Content-Type", "")))
    out: dict[str, str] = {}
    for item in payload.get("stockList", []):
        code = str(item.get("code", "")).strip()
        org_id = str(item.get("orgId", "")).strip()
        if code and org_id:
            out[code] = org_id
    return out


def _post_cninfo_disclosure_query(payload: dict[str, str], timeout_sec: int = 12) -> dict[str, Any]:
    """Submit one CNInfo disclosure query request and return the parsed JSON payload."""
    data = urlencode(payload).encode("utf-8")
    headers = {
        "User-Agent": _HTTP_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "http://www.cninfo.com.cn",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    }
    req = Request(_CNINFO_DISCLOSURE_QUERY_URL, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=timeout_sec) as resp:  # nosec B310 - fixed trusted host for public disclosure data
        return _decode_json_bytes(resp.read(), str(resp.headers.get("Content-Type", "")))


def _build_cninfo_report_links(
    symbol: str,
    org_id: str,
    announcement_id: str,
    announcement_time: str,
    adjunct_url: str | None,
) -> tuple[str, str | None]:
    """Build CNInfo detail and direct-document links for one disclosure entry."""
    query = urlencode(
        {
            "stockCode": symbol,
            "announcementId": announcement_id,
            "orgId": org_id,
            "announcementTime": announcement_time,
        }
    )
    detail_url = f"{_CNINFO_DISCLOSURE_DETAIL_BASE_URL}?{query}"

    document_url = None
    cleaned_adjunct = str(adjunct_url or "").strip()
    if cleaned_adjunct:
        document_url = urljoin(_CNINFO_STATIC_BASE_URL, cleaned_adjunct.lstrip("/"))
    return detail_url, document_url


def _score_annual_report_candidate(title: str, published_at: str) -> tuple[int, str, str]:
    """Score one annual-report candidate so the latest full report wins over summaries or notices."""
    normalized_title = str(title or "").replace(" ", "")
    normalized_date = str(published_at or "")
    score = 0
    if "年度报告" in normalized_title:
        score += 60
    if "年度报告全文" in normalized_title:
        score += 20
    if any(token in normalized_title for token in _CNINFO_FULL_YEAR_EXCLUDE_TOKENS):
        score -= 120
    if "公告" in normalized_title and "年度报告" not in normalized_title:
        score -= 40
    return score, normalized_date, normalized_title


def select_latest_annual_report(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the latest full annual report candidate from disclosure search results."""
    if not candidates:
        return None

    best = max(
        candidates,
        key=lambda item: _score_annual_report_candidate(
            title=str(item.get("title", "")),
            published_at=str(item.get("published_at", "")),
        ),
    )
    best_score, _, _ = _score_annual_report_candidate(
        title=str(best.get("title", "")),
        published_at=str(best.get("published_at", "")),
    )
    if best_score < 0:
        return None
    return best


def find_latest_annual_report(symbol: str, start_year: int | None = None, end_year: int | None = None) -> dict[str, Any]:
    """Find the latest full annual report disclosure entry for a stock symbol."""
    today = dt.date.today()
    query_end_year = end_year or today.year
    query_start_year = start_year or max(query_end_year - 3, 2000)

    org_map = _load_cninfo_symbol_org_map()
    org_id = org_map.get(symbol)
    if not org_id:
        raise RuntimeError(f"Could not resolve CNInfo orgId for symbol {symbol}.")

    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{symbol},{org_id}",
        "searchkey": "",
        "secid": "",
        "category": "category_ndbg_szsh",
        "trade": "",
        "seDate": f"{query_start_year}-01-01~{query_end_year}-12-31",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    result = _post_cninfo_disclosure_query(payload)

    candidates: list[dict[str, Any]] = []
    for item in result.get("announcements", []):
        title = str(item.get("announcementTitle", "")).strip()
        published_at = ""
        raw_ts = item.get("announcementTime")
        try:
            if raw_ts is not None:
                published_at = dt.datetime.fromtimestamp(float(raw_ts) / 1000, tz=dt.timezone.utc).astimezone(
                    dt.timezone(dt.timedelta(hours=8))
                ).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            published_at = ""
        announcement_id = str(item.get("announcementId", "")).strip()
        detail_url, document_url = _build_cninfo_report_links(
            symbol=symbol,
            org_id=str(item.get("orgId", org_id)).strip() or org_id,
            announcement_id=announcement_id,
            announcement_time=published_at,
            adjunct_url=str(item.get("adjunctUrl", "")).strip() or None,
        )
        candidates.append(
            {
                "symbol": symbol,
                "title": title,
                "published_at": published_at,
                "detail_url": detail_url,
                "document_url": document_url,
                "announcement_id": announcement_id or None,
                "source": "cninfo",
            }
        )

    selected = select_latest_annual_report(candidates)
    if not selected:
        raise RuntimeError(f"No full annual report was found for symbol {symbol}.")
    return selected


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
    # Financial logic: unitless cash-flow table cells are often local row fragments without the table header unit.
    if metric_name in {"operating_cash_flow", "capex_cash_outflow"} and unit == "":
        return False
    # Financial logic: amount metrics should not come from percentage values.
    if metric_name not in {"roe", "debt_ratio"} and unit == "%":
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
    prefer_after_keyword: bool,
    is_after_keyword: bool,
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
    if prefer_after_keyword:
        score += 12 if is_after_keyword else -12
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
    prefer_after_keyword: bool = False,
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

                absolute_start = snippet_start + num_match.start()
                distance = abs(absolute_start - kw_start)
                score = _score_candidate(
                    distance=distance,
                    unit=unit,
                    value=value,
                    require_percent=require_percent,
                    prefer_large_amount=prefer_large_amount,
                    prefer_after_keyword=prefer_after_keyword,
                    is_after_keyword=absolute_start >= kw_start,
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
    body, report_year, report_date = _build_report_text_body(text=text, title=title)

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
        keywords=["资产负债率"],
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


def extract_report_assessment_metrics(text: str, title: str | None = None) -> dict[str, Any]:
    """Extract additional profit-quality and capital-intensity metrics from report text."""
    base = extract_financial_row_from_report_text(text=text, title=title)
    body, report_year, report_date = _build_report_text_body(text=text, title=title)

    deducted_net_profit, deducted_net_profit_evidence = _best_metric_match(
        body,
        keywords=[
            "归属于上市公司股东的扣除非经常性损益的净利润",
            "扣除非经常性损益后的净利润",
            "扣非净利润",
        ],
        metric_name="deducted_net_profit",
        prefer_large_amount=True,
        prefer_after_keyword=True,
    )
    operating_cash_flow, operating_cash_flow_evidence = _best_metric_match(
        body,
        keywords=[
            "经营活动产生的现金流量净额",
            "经营现金流量净额",
            "经营活动现金流净额",
        ],
        metric_name="operating_cash_flow",
        prefer_large_amount=True,
        prefer_after_keyword=True,
    )
    capex_cash_outflow, capex_cash_outflow_evidence = _best_metric_match(
        body,
        keywords=[
            "购建固定资产、无形资产和其他长期资产支付的现金",
            "购建固定资产无形资产和其他长期资产支付的现金",
            "资本开支",
        ],
        metric_name="capex_cash_outflow",
        prefer_large_amount=True,
        prefer_after_keyword=True,
    )

    extra_warnings: list[str] = []
    if deducted_net_profit is None:
        extra_warnings.append("Deducted net profit was not reliably extracted.")
    if operating_cash_flow is None:
        extra_warnings.append("Operating cash flow was not reliably extracted.")
    if capex_cash_outflow is None:
        extra_warnings.append("Capex cash outflow was not reliably extracted.")

    evidence = [
        item
        for item in [
            *base.get("evidence", []),
            deducted_net_profit_evidence,
            operating_cash_flow_evidence,
            capex_cash_outflow_evidence,
        ]
        if item
    ]

    return {
        "report_year": report_year,
        "report_date": report_date,
        "revenue": base.get("revenue"),
        "net_profit": base.get("net_profit"),
        "deducted_net_profit": deducted_net_profit,
        "operating_cash_flow": operating_cash_flow,
        "roe": base.get("roe"),
        "debt_ratio": base.get("debt_ratio"),
        "capex_cash_outflow": capex_cash_outflow,
        "evidence": evidence,
        "warnings": [*base.get("warnings", []), *extra_warnings],
    }
