from __future__ import annotations

from collections import Counter
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
_OFFICIAL_DISCLOSURE_HOSTS = {
    "www.cninfo.com.cn",
    "static.cninfo.com.cn",
    "www.sse.com.cn",
    "static.sse.com.cn",
    "www.szse.cn",
    "disc.static.szse.cn",
}
_METRIC_NUM_RE = re.compile(r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)\s*(亿|万|元|%)?")
_SNIPPET_LEFT_CHARS = 20
_SNIPPET_RIGHT_CHARS = 120
_CNINFO_STOCK_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
_CNINFO_DISCLOSURE_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_DISCLOSURE_DETAIL_BASE_URL = "https://www.cninfo.com.cn/new/disclosure/detail"
_CNINFO_STATIC_BASE_URL = "https://static.cninfo.com.cn/"
_CNINFO_FULL_YEAR_EXCLUDE_TOKENS = ("摘要", "英文", "取消", "问询", "回复", "更正", "提示性公告")
_PDF_STRUCTURE_MARKERS = ("%pdf-", "endobj", "stream", "endstream", "xref", "trailer", "/type/", "/catalog")
_AUTOREAD_OVERVIEW_KEYWORDS = (
    "管理层讨论与分析",
    "经营情况讨论与分析",
    "主营业务",
    "收入",
    "利润",
    "增长",
    "海外",
    "渠道",
    "产品结构",
    "to b",
    "tob",
)
_AUTOREAD_AUTHENTICITY_KEYWORDS = (
    "扣除非经常性损益",
    "非经常性损益",
    "经营活动产生的现金流量净额",
    "现金流量净额",
    "回款",
    "政府补助",
    "公允价值",
    "会计政策",
)
_AUTOREAD_CAPITAL_KEYWORDS = (
    "资本开支",
    "购建固定资产",
    "无形资产",
    "长期资产",
    "在建工程",
    "固定资产",
    "产能",
    "工厂",
    "自动化",
    "扩产",
    "投资",
    "设备",
)
_AUTOREAD_RISK_KEYWORDS = ("风险", "关税", "汇率", "原材料", "需求", "价格波动")
_AUTOREAD_NOISE_KEYWORDS = ("目录", "重要提示", "释义", "公司简介", "股票简称")
_ANNUAL_REPORT_YEAR_RE = re.compile(r"(20\d{2})\s*年\s*年度报告(?:全文|摘要)?")
_AMOUNT_METRICS = {
    "revenue",
    "net_profit",
    "deducted_net_profit",
    "operating_cash_flow",
    "capex_cash_outflow",
}
_AMOUNT_UNIT_MULTIPLIERS = {
    "元": 1.0,
    "千元": 1_000.0,
    "万元": 10_000.0,
    "百万元": 1_000_000.0,
    "千万元": 10_000_000.0,
    "亿元": 100_000_000.0,
    "万": 10_000.0,
    "亿": 100_000_000.0,
}
_METRIC_NEGATIVE_CONTEXTS: dict[str, tuple[str, ...]] = {
    "net_profit": ("被合并方", "上期被合并方", "控制下企业合并"),
    "deducted_net_profit": ("被合并方", "上期被合并方", "控制下企业合并"),
    "debt_ratio": ("被担保对象", "担保金额", "担保余额", "担保总额", "债务担保"),
}
_METRIC_PRIMARY_CONTEXTS: dict[str, tuple[str, ...]] = {
    "revenue": ("主要会计数据和财务指标", "本年比上年增减", "营业收入"),
    "net_profit": ("主要会计数据和财务指标", "归属于上市公司股东的净利润", "本年比上年增减"),
    "deducted_net_profit": ("主要会计数据和财务指标", "扣除非经常性损益", "本年比上年增减"),
    "debt_ratio": ("流动比率", "速动比率", "EBITDA全部债务比", "利息保障倍数"),
}
REPORT_EXTRACTION_VERSION = 2


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


def _validate_official_report_url(url: str, *, redirected: bool = False) -> None:
    """Allow only explicitly supported official disclosure hosts for report fetching."""
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("URL must be a valid http(s) address.")
    if host in _OFFICIAL_DISCLOSURE_HOSTS:
        return
    if redirected:
        raise RuntimeError(
            "Report URL redirected to a non-whitelisted host. "
            "Only official disclosure sources are supported."
        )
    raise ValueError("URL must use one of the supported official disclosure sources.")


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

    title_year_match = _ANNUAL_REPORT_YEAR_RE.search(str(title or ""))
    head_annual_year_match = _ANNUAL_REPORT_YEAR_RE.search(body[:8000])
    year_candidates = [int(item) for item in re.findall(r"(20\d{2})\s*年", body)]
    date_match = re.search(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?", body)

    report_year = int(title_year_match.group(1)) if title_year_match else None
    if report_year is None:
        report_year = int(head_annual_year_match.group(1)) if head_annual_year_match else None
    if report_year is None and year_candidates:
        year_counts = Counter(year_candidates)
        report_year = max(year_counts.items(), key=lambda item: (item[1], item[0]))[0]
    report_date: str | None = None
    if report_year is not None:
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


def _split_autoread_segments(text: str, title: str | None = None) -> list[str]:
    """Split report text into candidate segments while keeping semantically useful boundaries."""
    raw = ((title or "") + "\n" + (text or "")).replace("\r\n", "\n").replace("\r", "\n")
    block_candidates = [item.strip() for item in re.split(r"\n{2,}", raw) if item.strip()]
    if len(block_candidates) >= 6:
        segments = block_candidates
    else:
        segments = [item.strip() for item in re.split(r"(?<=[。！？；;])\s+|\n+", raw) if item.strip()]

    normalized_segments: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        cleaned = re.sub(r"\s+", " ", segment).strip()
        if len(cleaned) < 12:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized_segments.append(cleaned)
    return normalized_segments


def _score_autoread_segment(segment: str, keywords: tuple[str, ...]) -> int:
    """Score one segment for a specific retrieval theme."""
    normalized = segment.lower()
    score = sum(1 for keyword in keywords if keyword.lower() in normalized) * 3
    score += min(len(segment) // 80, 3)
    if any(noise.lower() in normalized for noise in _AUTOREAD_NOISE_KEYWORDS):
        score -= 2
    return score


def _pick_segments_for_keywords(
    segments: list[str],
    keywords: tuple[str, ...],
    *,
    used: set[str],
    max_items: int,
) -> list[str]:
    """Pick top unique segments for one keyword theme."""
    ranked = [
        (score, len(segment), index, segment)
        for index, segment in enumerate(segments)
        if segment not in used and (score := _score_autoread_segment(segment, keywords)) > 0
    ]
    ranked.sort(reverse=True)
    selected: list[str] = []
    for _score, _length, _index, segment in ranked:
        selected.append(segment)
        used.add(segment)
        if len(selected) >= max_items:
            break
    return selected


def build_autoread_llm_excerpt(text: str, title: str | None = None, max_chars: int = 6000) -> str:
    """Build a compact report excerpt focused on the three autoread questions."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    segments = _split_autoread_segments(text, title=title)
    if not segments:
        return ""

    # Financial logic: select evidence in question order so profit quality, sustainability,
    # and capital intensity all keep at least one supporting segment when possible.
    used: set[str] = set()
    selected: list[str] = []
    if title:
        selected.append(title.strip())
        used.add(title.strip())

    for keyword_group, limit in (
        (_AUTOREAD_OVERVIEW_KEYWORDS, 2),
        (_AUTOREAD_AUTHENTICITY_KEYWORDS, 2),
        (_AUTOREAD_CAPITAL_KEYWORDS, 2),
        (_AUTOREAD_RISK_KEYWORDS, 1),
    ):
        selected.extend(_pick_segments_for_keywords(segments, keyword_group, used=used, max_items=limit))

    if len(selected) < 4:
        for segment in segments:
            if segment in used:
                continue
            selected.append(segment)
            used.add(segment)
            if len(selected) >= 6:
                break

    excerpt_parts: list[str] = []
    current_length = 0
    for segment in selected:
        addition = segment if not excerpt_parts else f"\n\n{segment}"
        if excerpt_parts and current_length + len(addition) > max_chars:
            continue
        if not excerpt_parts and len(segment) > max_chars:
            excerpt_parts.append(segment[:max_chars].strip())
            break
        excerpt_parts.append(segment)
        current_length += len(addition)

    return "\n\n".join(excerpt_parts).strip()


def _load_cninfo_symbol_org_map(timeout_sec: int = 12) -> dict[str, str]:
    """Load CNInfo stock-code to org-id mapping for report disclosure queries."""
    req = Request(_CNINFO_STOCK_MAP_URL, headers={"User-Agent": _HTTP_USER_AGENT})
    ssl_context = _build_verified_ssl_context()
    with urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:  # nosec B310 - fixed trusted host for public disclosure data
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
        "Origin": "https://www.cninfo.com.cn",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    }
    req = Request(_CNINFO_DISCLOSURE_QUERY_URL, data=data, headers=headers, method="POST")
    ssl_context = _build_verified_ssl_context()
    with urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:  # nosec B310 - fixed trusted host for public disclosure data
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
    pdf_max_bytes: int = 120_000_000,
) -> dict[str, Any]:
    """Fetch report page text from URL, with basic safety guards."""
    parsed = urlparse(url.strip())
    _validate_official_report_url(url)
    path_is_pdf = parsed.path.lower().endswith(".pdf")

    pdf_limit_bytes = _parse_mb_env("REPORT_PDF_MAX_MB", default_mb=max(1, pdf_max_bytes // 1_000_000)) * 1_000_000
    html_limit_bytes = _parse_mb_env("REPORT_HTML_MAX_MB", default_mb=max(1, max_bytes // 1_000_000)) * 1_000_000

    req = Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
    insecure_ssl_used = False
    try:
        ssl_context = _build_verified_ssl_context()
        with urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:  # nosec B310 - validated scheme and controlled usage
            _validate_official_report_url(resp.geturl() or url, redirected=True)
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
                _validate_official_report_url(resp.geturl() or url, redirected=True)
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
    normalized_unit = str(unit or "").replace("人民币", "").replace(" ", "").strip()
    if normalized_unit in _AMOUNT_UNIT_MULTIPLIERS:
        return value * _AMOUNT_UNIT_MULTIPLIERS[normalized_unit]
    return value


def _get_snippet_window(text: str, keyword_start: int) -> tuple[str, int]:
    """Return local snippet around a keyword plus snippet start offset."""
    snippet_start = max(0, keyword_start - _SNIPPET_LEFT_CHARS)
    snippet_end = min(len(text), keyword_start + _SNIPPET_RIGHT_CHARS)
    return text[snippet_start:snippet_end], snippet_start


def _get_metric_context_window(text: str, keyword_start: int) -> str:
    """Return a wider local window around a metric keyword for context-sensitive scoring."""
    start = max(0, keyword_start - 260)
    end = min(len(text), keyword_start + 220)
    return text[start:end]


def _get_candidate_local_context(text: str, absolute_start: int) -> str:
    """Return a tight local window around one numeric candidate."""
    start = max(0, absolute_start - 80)
    end = min(len(text), absolute_start + 100)
    return text[start:end]


def _infer_unit_context(metric_name: str, context_text: str, inline_unit: str) -> str:
    """Infer amount units from nearby table headers when cells omit explicit unit text."""
    if inline_unit:
        return inline_unit
    normalized_context = re.sub(r"\s+", "", context_text)

    if metric_name == "roe":
        if re.search(r"(加权平均)?净资产收益率[（(]?[％%][）)]?", normalized_context):
            return "%"
    if metric_name == "debt_ratio":
        if re.search(r"资产负债率[（(]?[％%][）)]?", normalized_context):
            return "%"

    if metric_name not in _AMOUNT_METRICS:
        return inline_unit
    normalized_context = re.sub(r"\s+", " ", context_text)
    matches = list(
        re.finditer(r"单位\s*[:：]\s*(?:人民币)?\s*(千万元|百万元|千元|万元|亿元|元)", normalized_context)
    )
    if not matches:
        return inline_unit
    return matches[-1].group(1)


def _candidate_context_adjustment(metric_name: str, context_text: str, local_context_text: str) -> float:
    """Apply semantic bonuses/penalties based on local financial-table context."""
    local_normalized = re.sub(r"\s+", "", local_context_text)
    if any(token in local_normalized for token in _METRIC_NEGATIVE_CONTEXTS.get(metric_name, ())):
        return -400.0

    normalized = re.sub(r"\s+", "", context_text)
    score = 0.0
    if any(token in normalized for token in _METRIC_PRIMARY_CONTEXTS.get(metric_name, ())):
        score += 35.0
    if metric_name in _AMOUNT_METRICS and "单位：" in normalized:
        score += 8.0
    return score


def _looks_like_section_enumerator(metric_name: str, number_text: str, inline_unit: str, snippet: str, match_start: int, match_end: int) -> bool:
    """Reject outline indices such as '1）营业收入整体情况' for amount metrics."""
    if metric_name not in _AMOUNT_METRICS or inline_unit:
        return False
    normalized_number = number_text.replace(",", "").strip()
    if not normalized_number.isdigit():
        return False
    if int(normalized_number) > 20:
        return False

    prev_char = snippet[match_start - 1] if match_start > 0 else ""
    next_char = snippet[match_end] if match_end < len(snippet) else ""
    return prev_char in {"（", "("} or next_char in {"）", ")", "、", ".", "．"}


def _looks_like_partial_year_or_number(snippet: str, match_start: int, match_end: int) -> bool:
    """Reject numeric fragments that are only part of a longer year/number token."""
    prev_char = snippet[match_start - 1] if match_start > 0 else ""
    next_char = snippet[match_end] if match_end < len(snippet) else ""
    if prev_char.isdigit() or next_char.isdigit():
        return True
    return prev_char in {"年", "月", "日"} or next_char in {"年", "月", "日"}


def _looks_like_note_reference(line: str, number_text: str, inline_unit: str, match_start: int, match_end: int) -> bool:
    """Reject note indices such as '七、25' before the actual balance-sheet amount."""
    if inline_unit:
        return False
    if "," in number_text or "." in number_text:
        return False
    normalized_number = number_text.replace(",", "").strip()
    if not normalized_number.isdigit():
        return False
    if int(normalized_number) > 99:
        return False
    trailing = line[match_end : min(len(line), match_end + 12)]
    if re.match(r"\s+[0-9][0-9,\.]*", trailing):
        return True
    prefix = line[max(0, match_start - 4) : match_start]
    return any(token in prefix for token in ("七、", "七（", "附注", "注", "（", "("))


def _clean_evidence_snippet(metric_name: str, snippet: str, number_text: str) -> str:
    """Trim evidence text before known misleading follow-up phrases when possible."""
    cleaned = snippet.strip()
    number_index = cleaned.find(number_text)
    if number_index >= 0:
        cut_positions = [
            position
            for token in _METRIC_NEGATIVE_CONTEXTS.get(metric_name, ())
            if (position := cleaned.find(token)) > number_index
        ]
        if cut_positions:
            cleaned = cleaned[: min(cut_positions)].rstrip(" ，,。；;")
    return cleaned[:180]


def _normalized_report_lines(text: str, title: str | None = None) -> list[str]:
    """Normalize report text into non-empty lines while preserving table-like row boundaries."""
    raw = ((title or "") + "\n" + (text or "")).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in raw.split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _report_lines_with_unit_context(text: str, title: str | None = None) -> list[tuple[str, str | None]]:
    """Return normalized report lines with the latest visible amount-unit header carried forward."""
    lines = _normalized_report_lines(text, title=title)
    output: list[tuple[str, str | None]] = []
    current_unit: str | None = None
    for line in lines:
        unit_match = re.search(r"单位\s*[:：]\s*(?:人民币)?\s*(千万元|百万元|千元|万元|亿元|元)", line)
        if unit_match:
            current_unit = unit_match.group(1)
        output.append((line, current_unit))
    return output


def _primary_metrics_section_lines(text: str, title: str | None = None) -> list[tuple[str, str | None]]:
    """Return normalized lines within the annual-report primary metrics section."""
    lines = _normalized_report_lines(text, title=title)
    start_index: int | None = None
    for idx, line in enumerate(lines):
        if "主要会计数据和财务指标" in line:
            start_index = idx
            break
    if start_index is None:
        return []

    section: list[tuple[str, str | None]] = []
    current_unit: str | None = None
    for line in lines[start_index : start_index + 120]:
        if section and (
            line.startswith("六、")
            or line.startswith("七、")
            or line.startswith("第三节")
            or "分季度主要财务指标" in line
            or "管理层讨论与分析" in line
        ):
            break
        unit_match = re.search(r"单位\s*[:：]\s*(千万元|百万元|千元|万元|亿元|元)", line)
        if unit_match:
            current_unit = unit_match.group(1)
        section.append((line, current_unit))
    return section


def _extract_table_amount_metric(
    section_lines: list[tuple[str, str | None]],
    *,
    metric_name: str,
    include_tokens: tuple[str, ...],
    exclude_tokens: tuple[str, ...] = (),
) -> tuple[float | None, dict[str, Any] | None]:
    """Extract the first primary-table amount candidate from the annual-report metrics section."""
    for line, section_unit in section_lines:
        normalized = line.replace(" ", "")
        if not all(token in normalized for token in include_tokens):
            continue
        if any(token in normalized for token in exclude_tokens):
            continue

        keyword_pos = min((line.find(token) for token in include_tokens if token in line), default=-1)
        if keyword_pos < 0:
            continue

        for num_match in _METRIC_NUM_RE.finditer(line):
            if num_match.start(1) < keyword_pos:
                continue

            number_text = num_match.group(1)
            inline_unit = num_match.group(2) or ""
            if _looks_like_section_enumerator(
                metric_name,
                number_text,
                inline_unit,
                line,
                num_match.start(1),
                num_match.end(1),
            ):
                continue
            if _looks_like_note_reference(line, number_text, inline_unit, num_match.start(1), num_match.end(1)):
                continue
            if _looks_like_partial_year_or_number(line, num_match.start(1), num_match.end(1)):
                continue

            effective_unit = inline_unit or (section_unit if metric_name in _AMOUNT_METRICS else inline_unit)
            value = _to_numeric_value(number_text, effective_unit)
            if value is None:
                continue
            if not _is_candidate_valid(metric_name, effective_unit, value, require_percent=False):
                continue

            evidence = _build_candidate_evidence(
                metric_name=metric_name,
                keyword=include_tokens[0],
                number_text=number_text,
                unit=inline_unit,
                unit_context=effective_unit if effective_unit and effective_unit != inline_unit else None,
                snippet=line,
                distance=max(0, num_match.start(1) - keyword_pos),
                score=500.0,
                parsed_value=value,
            )
            return value, evidence
    return None, None


def _extract_line_amount_metric(
    lines: list[tuple[str, str | None]],
    *,
    metric_name: str,
    keywords: tuple[str, ...],
    exclude_tokens: tuple[str, ...] = (),
) -> tuple[float | None, dict[str, Any] | None]:
    """Extract one amount metric from a single report line before fuzzy matching."""
    normalized_excludes = tuple(token.replace(" ", "") for token in exclude_tokens)

    for idx, (line, carried_unit) in enumerate(lines):
        candidate_lines: list[tuple[str, str | None]] = [(line, carried_unit)]
        if idx + 1 < len(lines):
            next_line, next_unit = lines[idx + 1]
            candidate_lines.append((f"{line}{next_line}", carried_unit or next_unit))

        for candidate_line, candidate_unit in candidate_lines:
            normalized_line = re.sub(r"\s+", "", candidate_line)
            if any(token and token in normalized_line for token in normalized_excludes):
                continue

            for keyword in keywords:
                key_match = re.search(_build_loose_keyword_pattern(keyword), candidate_line, flags=re.IGNORECASE)
                if not key_match:
                    continue

                keyword_context = candidate_line[key_match.start() : min(len(candidate_line), key_match.end() + 16)]
                inline_context_unit_match = re.search(r"[（(]?(千万元|百万元|千元|万元|亿元|元)[）)]?", keyword_context)
                inline_context_unit = inline_context_unit_match.group(1) if inline_context_unit_match else ""

                for num_match in _METRIC_NUM_RE.finditer(candidate_line):
                    if num_match.start(1) < key_match.end():
                        continue

                    number_text = num_match.group(1)
                    inline_unit = num_match.group(2) or ""
                    if _looks_like_note_reference(candidate_line, number_text, inline_unit, num_match.start(1), num_match.end(1)):
                        continue
                    if _looks_like_partial_year_or_number(candidate_line, num_match.start(1), num_match.end(1)):
                        continue
                    effective_unit = inline_unit or inline_context_unit or candidate_unit or ""
                    value = _to_numeric_value(number_text, effective_unit)
                    if value is None:
                        continue
                    if not _is_candidate_valid(metric_name, effective_unit, value, require_percent=False):
                        continue

                    evidence = _build_candidate_evidence(
                        metric_name=metric_name,
                        keyword=keyword,
                        number_text=number_text,
                        unit=inline_unit,
                        unit_context=effective_unit if effective_unit and effective_unit != inline_unit else None,
                        snippet=candidate_line,
                        distance=max(0, num_match.start(1) - key_match.start()),
                        score=610.0,
                        parsed_value=value,
                    )
                    return value, evidence
    return None, None


def _extract_line_percent_metric(
    lines: list[str],
    *,
    metric_name: str,
    keywords: tuple[str, ...],
    exclude_tokens: tuple[str, ...] = (),
) -> tuple[float | None, dict[str, Any] | None]:
    """Extract one percent metric from a single report line before global fuzzy matching."""
    normalized_excludes = tuple(token.replace(" ", "") for token in exclude_tokens)

    for line in lines:
        normalized_line = re.sub(r"\s+", "", line)
        if any(token and token in normalized_line for token in normalized_excludes):
            continue

        for keyword in keywords:
            key_match = re.search(_build_loose_keyword_pattern(keyword), line, flags=re.IGNORECASE)
            if not key_match:
                continue

            keyword_context = line[key_match.start() : min(len(line), key_match.end() + 12)]
            percent_unit = "%" if re.search(r"[（(]?[％%][）)]?", keyword_context) else ""
            for num_match in _METRIC_NUM_RE.finditer(line):
                if num_match.start(1) < key_match.end():
                    continue

                number_text = num_match.group(1)
                inline_unit = num_match.group(2) or ""
                effective_unit = inline_unit or percent_unit
                value = _to_numeric_value(number_text, effective_unit)
                if value is None:
                    continue
                if not _is_candidate_valid(metric_name, effective_unit, value, require_percent=True):
                    continue

                evidence = _build_candidate_evidence(
                    metric_name=metric_name,
                    keyword=keyword,
                    number_text=number_text,
                    unit=inline_unit,
                    unit_context=effective_unit if effective_unit and effective_unit != inline_unit else None,
                    snippet=line,
                    distance=max(0, num_match.start(1) - key_match.start()),
                    score=600.0,
                    parsed_value=value,
                )
                return value, evidence
    return None, None


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
    unit_context: str | None,
    snippet: str,
    distance: int,
    score: float,
    parsed_value: float,
) -> dict[str, Any]:
    """Build evidence payload for explainability and debugging."""
    payload = {
        "metric": metric_name,
        "keyword": keyword,
        "raw_number": f"{number_text}{unit}",
        "parsed_value": parsed_value,
        "distance": distance,
        "score": score,
        "snippet": _clean_evidence_snippet(metric_name, snippet, number_text),
    }
    if unit_context:
        payload["unit_context"] = unit_context
    return payload


def _build_loose_keyword_pattern(keyword: str) -> str:
    """Allow PDF-extracted text to insert whitespace inside metric labels."""
    chars = list(str(keyword or ""))
    parts: list[str] = []
    for idx, char in enumerate(chars):
        if char.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(char))
        if idx < len(chars) - 1 and not char.isspace() and not chars[idx + 1].isspace():
            parts.append(r"\s*")
    return "".join(parts)


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
        keyword_pattern = _build_loose_keyword_pattern(keyword)
        for key_match in re.finditer(keyword_pattern, text, flags=re.IGNORECASE):
            kw_start = key_match.start()
            snippet, snippet_start = _get_snippet_window(text, kw_start)
            context_text = _get_metric_context_window(text, kw_start)
            for num_match in _METRIC_NUM_RE.finditer(snippet):
                number_text = num_match.group(1)
                inline_unit = num_match.group(2) or ""
                if _looks_like_section_enumerator(
                    metric_name,
                    number_text,
                    inline_unit,
                    snippet,
                    num_match.start(1),
                    num_match.end(1),
                ):
                    continue
                if _looks_like_partial_year_or_number(snippet, num_match.start(1), num_match.end(1)):
                    continue
                effective_unit = _infer_unit_context(metric_name, context_text, inline_unit)
                value = _to_numeric_value(number_text, effective_unit)
                if value is None:
                    continue

                if not _is_candidate_valid(metric_name, effective_unit, value, require_percent):
                    continue

                absolute_start = snippet_start + num_match.start()
                local_context_text = _get_candidate_local_context(text, absolute_start)
                distance = abs(absolute_start - kw_start)
                score = _score_candidate(
                    distance=distance,
                    unit=effective_unit,
                    value=value,
                    require_percent=require_percent,
                    prefer_large_amount=prefer_large_amount,
                    prefer_after_keyword=prefer_after_keyword,
                    is_after_keyword=absolute_start >= kw_start,
                )
                score += _candidate_context_adjustment(metric_name, context_text, local_context_text)
                evidence = _build_candidate_evidence(
                    metric_name=metric_name,
                    keyword=keyword,
                    number_text=number_text,
                    unit=inline_unit,
                    unit_context=effective_unit if effective_unit and effective_unit != inline_unit else None,
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
    section_lines = _primary_metrics_section_lines(text, title=title)
    section_only_lines = [line for line, _unit in section_lines]
    all_lines = _normalized_report_lines(text, title=title)
    all_lines_with_units = _report_lines_with_unit_context(text, title=title)

    revenue, revenue_evidence = _extract_table_amount_metric(
        section_lines,
        metric_name="revenue",
        include_tokens=("营业收入",),
        exclude_tokens=("营业收入整体情况", "营业收入构成"),
    )
    if revenue is None:
        revenue, revenue_evidence = _best_metric_match(
            body,
            keywords=["营业总收入", "营业收入", "主营业务收入"],
            metric_name="revenue",
            prefer_large_amount=True,
        )

    net_profit, net_profit_evidence = _extract_table_amount_metric(
        section_lines,
        metric_name="net_profit",
        include_tokens=("归属于上市公司股东", "净利润"),
        exclude_tokens=("扣除非经常性损益",),
    )
    if net_profit is None:
        net_profit, net_profit_evidence = _best_metric_match(
            body,
            keywords=["归属于上市公司股东的净利润", "归母净利润", "净利润"],
            metric_name="net_profit",
            prefer_large_amount=True,
        )
    total_assets, total_assets_evidence = _extract_line_amount_metric(
        section_lines,
        metric_name="total_assets",
        keywords=("总资产", "资产总计", "资产总额"),
        exclude_tokens=("占总资产比例", "总资产比例", "境外资产"),
    )
    if total_assets is None:
        total_assets, total_assets_evidence = _extract_line_amount_metric(
            all_lines_with_units,
            metric_name="total_assets",
            keywords=("总资产", "资产总计", "资产总额"),
            exclude_tokens=("占总资产比例", "总资产比例", "境外资产", "总资产的比例"),
        )
    attributable_equity, attributable_equity_evidence = _extract_line_amount_metric(
        section_lines,
        metric_name="attributable_equity",
        keywords=("归属于上市公司股东的净资产", "归属于母公司所有者权益", "归属于母公司股东权益"),
        exclude_tokens=("净资产差异", "净资产收益率"),
    )
    if attributable_equity is None:
        attributable_equity, attributable_equity_evidence = _extract_line_amount_metric(
            all_lines_with_units,
            metric_name="attributable_equity",
            keywords=("归属于上市公司股东的净资产", "归属于母公司所有者权益", "归属于母公司股东权益"),
            exclude_tokens=("净资产差异", "净资产收益率"),
        )
    total_liabilities, total_liabilities_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="total_liabilities",
        keywords=("负债合计", "总负债"),
        exclude_tokens=("流动负债合计", "非流动负债合计", "负债和所有者权益总计"),
    )
    net_assets, net_assets_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="net_assets",
        keywords=("所有者权益合计", "股东权益合计", "所有者权益（或股东权益）合计", "所有者权益（或股东权 益）合计"),
        exclude_tokens=("负债和所有者权益总计",),
    )
    if net_assets is None:
        if total_assets is not None and total_liabilities is not None:
            net_assets = total_assets - total_liabilities
        elif attributable_equity is not None:
            net_assets = attributable_equity
    monetary_funds, monetary_funds_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="monetary_funds",
        keywords=("货币资金",),
    )
    accounts_receivable, accounts_receivable_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="accounts_receivable",
        keywords=("应收账款",),
        exclude_tokens=("客户应收账款",),
    )
    inventory, inventory_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="inventory",
        keywords=("存货",),
        exclude_tokens=("存货风险", "存货跌价准备", "存货成本高于其可变现净值", "存货减值"),
    )
    fixed_assets, fixed_assets_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="fixed_assets",
        keywords=("固定资产",),
        exclude_tokens=("购建固定资产", "处置固定资产", "固定资产投资", "转入固定资产", "固定资产、无形资产"),
    )
    construction_in_progress, construction_in_progress_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="construction_in_progress",
        keywords=("在建工程",),
        exclude_tokens=("重要在建工程项目", "在建工程等项目", "在建工程项目情况"),
    )
    goodwill, goodwill_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="goodwill",
        keywords=("商誉",),
        exclude_tokens=("账面价值为", "关键审计事项", "审计中的应对", "商誉减值", "使用寿命不确定", "长期待摊费用"),
    )
    short_term_borrowings, short_term_borrowings_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="interest_bearing_debt",
        keywords=("短期借款",),
    )
    current_non_current_debt, current_non_current_debt_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="interest_bearing_debt",
        keywords=("一年内到期的非流动负债",),
    )
    long_term_borrowings, long_term_borrowings_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="interest_bearing_debt",
        keywords=("长期借款",),
    )
    bonds_payable, bonds_payable_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="interest_bearing_debt",
        keywords=("应付债券",),
    )
    lease_liabilities, lease_liabilities_evidence = _extract_line_amount_metric(
        all_lines_with_units,
        metric_name="interest_bearing_debt",
        keywords=("租赁负债",),
    )
    interest_bearing_components = [
        value
        for value in (
            short_term_borrowings,
            current_non_current_debt,
            long_term_borrowings,
            bonds_payable,
            lease_liabilities,
        )
        if value is not None
    ]
    interest_bearing_debt = sum(interest_bearing_components) if interest_bearing_components else None
    interest_bearing_debt_evidence = None
    if interest_bearing_debt is not None:
        interest_bearing_debt_evidence = {
            "metric": "interest_bearing_debt",
            "keyword": "derived_sum",
            "raw_number": " + ".join(
                key
                for key, value in (
                    ("short_term_borrowings", short_term_borrowings),
                    ("current_non_current_debt", current_non_current_debt),
                    ("long_term_borrowings", long_term_borrowings),
                    ("bonds_payable", bonds_payable),
                    ("lease_liabilities", lease_liabilities),
                )
                if value is not None
            ),
            "parsed_value": interest_bearing_debt,
            "distance": 0,
            "score": 620.0,
            "snippet": "derived from short/long debt, current portion, bonds, and lease liabilities",
        }

    roe, roe_evidence = _extract_line_percent_metric(
        section_only_lines,
        metric_name="roe",
        keywords=("净资产收益率", "ROE", "roe"),
    )
    if roe is None:
        roe, roe_evidence = _extract_line_percent_metric(
            all_lines,
            metric_name="roe",
            keywords=("净资产收益率", "ROE", "roe"),
        )
    if roe is None:
        roe, roe_evidence = _best_metric_match(
            body,
            keywords=["净资产收益率", "ROE", "roe"],
            metric_name="roe",
            require_percent=True,
            prefer_after_keyword=True,
        )
    debt_ratio, debt_evidence = _extract_line_percent_metric(
        section_only_lines,
        metric_name="debt_ratio",
        keywords=("资产负债率",),
        exclude_tokens=("被担保对象", "担保金额", "担保余额", "担保总额", "债务担保", "超过70%"),
    )
    if debt_ratio is None:
        debt_ratio, debt_evidence = _extract_line_percent_metric(
            all_lines,
            metric_name="debt_ratio",
            keywords=("资产负债率",),
            exclude_tokens=("被担保对象", "担保金额", "担保余额", "担保总额", "债务担保", "超过70%"),
        )

    evidence = [
        item
        for item in [
            revenue_evidence,
            net_profit_evidence,
            total_assets_evidence,
            attributable_equity_evidence,
            total_liabilities_evidence,
            net_assets_evidence,
            monetary_funds_evidence,
            accounts_receivable_evidence,
            inventory_evidence,
            fixed_assets_evidence,
            construction_in_progress_evidence,
            goodwill_evidence,
            short_term_borrowings_evidence,
            current_non_current_debt_evidence,
            long_term_borrowings_evidence,
            bonds_payable_evidence,
            lease_liabilities_evidence,
            interest_bearing_debt_evidence,
            roe_evidence,
            debt_evidence,
        ]
        if item
    ]
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
        "extraction_version": REPORT_EXTRACTION_VERSION,
        "report_year": report_year,
        "report_date": report_date,
        "revenue": revenue,
        "net_profit": net_profit,
        "total_assets": total_assets,
        "net_assets": net_assets,
        "attributable_equity": attributable_equity,
        "total_liabilities": total_liabilities,
        "monetary_funds": monetary_funds,
        "accounts_receivable": accounts_receivable,
        "inventory": inventory,
        "fixed_assets": fixed_assets,
        "construction_in_progress": construction_in_progress,
        "goodwill": goodwill,
        "interest_bearing_debt": interest_bearing_debt,
        "roe": roe,
        "debt_ratio": debt_ratio,
        "evidence": evidence,
        "warnings": warnings,
    }


def extract_report_assessment_metrics(text: str, title: str | None = None) -> dict[str, Any]:
    """Extract additional profit-quality and capital-intensity metrics from report text."""
    base = extract_financial_row_from_report_text(text=text, title=title)
    body, report_year, report_date = _build_report_text_body(text=text, title=title)
    section_lines = _primary_metrics_section_lines(text, title=title)
    all_lines_with_units = _report_lines_with_unit_context(text, title=title)

    deducted_net_profit, deducted_net_profit_evidence = _extract_table_amount_metric(
        section_lines,
        metric_name="deducted_net_profit",
        include_tokens=("归属于上市公司股东的扣除非经常性损益的净利润",),
    )
    if deducted_net_profit is None:
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
    operating_cash_flow, operating_cash_flow_evidence = _extract_table_amount_metric(
        section_lines,
        metric_name="operating_cash_flow",
        include_tokens=("经营活动产生的现金流量净额",),
    )
    if operating_cash_flow is None:
        operating_cash_flow, operating_cash_flow_evidence = _extract_line_amount_metric(
            all_lines_with_units,
            metric_name="operating_cash_flow",
            keywords=("经营活动产生的现金流量净额", "经营现金流量净额", "经营活动现金流净额"),
        )
    if operating_cash_flow is None:
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
    capex_cash_outflow, capex_cash_outflow_evidence = _extract_table_amount_metric(
        section_lines,
        metric_name="capex_cash_outflow",
        include_tokens=("购建固定资产", "长期资产支付的现金"),
    )
    if capex_cash_outflow is None:
        capex_cash_outflow, capex_cash_outflow_evidence = _extract_line_amount_metric(
            all_lines_with_units,
            metric_name="capex_cash_outflow",
            keywords=(
                "购建固定资产、无形资产和其他长期资产支付的现金",
                "购建固定资产无形资产和其他长期资产支付的现金",
                "购建固定资产",
                "长期资产支付的现金",
                "资本开支",
            ),
        )
    if capex_cash_outflow is None:
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
        "extraction_version": REPORT_EXTRACTION_VERSION,
        "report_year": report_year,
        "report_date": report_date,
        "revenue": base.get("revenue"),
        "net_profit": base.get("net_profit"),
        "total_assets": base.get("total_assets"),
        "net_assets": base.get("net_assets"),
        "attributable_equity": base.get("attributable_equity"),
        "total_liabilities": base.get("total_liabilities"),
        "monetary_funds": base.get("monetary_funds"),
        "accounts_receivable": base.get("accounts_receivable"),
        "inventory": base.get("inventory"),
        "fixed_assets": base.get("fixed_assets"),
        "construction_in_progress": base.get("construction_in_progress"),
        "goodwill": base.get("goodwill"),
        "interest_bearing_debt": base.get("interest_bearing_debt"),
        "deducted_net_profit": deducted_net_profit,
        "operating_cash_flow": operating_cash_flow,
        "roe": base.get("roe"),
        "debt_ratio": base.get("debt_ratio"),
        "capex_cash_outflow": capex_cash_outflow,
        "evidence": evidence,
        "warnings": [*base.get("warnings", []), *extra_warnings],
    }
