from __future__ import annotations

import copy
import logging
import re
import threading
from typing import Any

from app.db import fetch_report_artifact
from app.services.llm_service import answer_report_question_with_llm
from app.services import report_context_service


REPORT_CONTEXT_CACHE_MAX_ENTRIES = 8
REPORT_QA_HISTORY_MAX_TURNS = 6
REPORT_SCOPE_KEYWORDS = (
    "利润",
    "净利",
    "收入",
    "营收",
    "现金流",
    "增长",
    "毛利",
    "毛利率",
    "净利率",
    "业绩",
    "风险",
    "业务",
    "经营",
    "成本",
    "费用",
    "资本",
    "capex",
    "revenue",
    "profit",
    "cash flow",
    "margin",
    "report",
    "annual report",
    "年报",
    "半年报",
    "季报",
    "公告",
)
REPORT_FOLLOW_UP_KEYWORDS = (
    "为什么",
    "怎么",
    "为何",
    "原因",
    "展开",
    "讲讲",
    "细说",
    "详细",
    "补充",
    "再说",
    "多说",
    "来自",
    "改善",
    "变化",
    "影响",
    "是否",
    "能否",
    "如何",
    "what",
    "why",
    "how",
    "cause",
    "driver",
)
REPORT_QA_NUMERIC_SUPPORT_LABELS = (
    "归属于上市公司股东的扣除非经常性损益的净利润",
    "归属于上市公司股东的净利润",
    "经营活动产生的现金流量净额",
    "营业总收入",
    "营业收入",
    "扣非净利润",
    "净利润",
    "资本开支",
)
DIRECT_METRIC_QUESTION_HINTS = ("多少", "几", "分别", "是多少", "为多少")
REPORT_DRIVER_QUESTION_HINTS = ("来自哪里", "主要来自", "驱动", "来源", "为什么增长", "增长原因", "改善原因")
REPORT_CASHFLOW_MATCH_QUESTION_HINTS = ("匹配吗", "匹配度", "匹配", "对应得上", "覆盖得住")
REPORT_PROFIT_AUTHENTICITY_HINTS = ("净利润较为真实", "利润较为真实", "净利润是否为真", "利润是否为真", "利润质量", "真实性")
GENERIC_FOLLOW_UP_PREFIXES = (
    "能展开",
    "展开讲",
    "展开一点",
    "展开下",
    "具体一点",
    "再具体",
    "细说",
    "详细说",
    "多说",
    "补充",
    "继续",
    "也没有展开",
    "没有展开",
    "没展开",
    "什么意思",
    "然后呢",
)
OUT_OF_SCOPE_KEYWORDS = (
    "买入",
    "卖出",
    "目标价",
    "目标价格",
    "推荐",
    "建议",
    "值不值得买",
    "值得买吗",
    "能买吗",
    "该买吗",
    "buy",
    "sell",
    "price target",
    "portfolio",
    "持仓",
    "炒股",
    "投顾",
    "股价",
    "现价",
    "市值",
    "行情",
    "涨跌",
    "涨跌幅",
    "收盘",
    "开盘",
    "成交量",
    "市盈率",
    "市净率",
    "pe",
    "pb",
    "天气",
    "电影",
    "足球",
    "明星",
)
_REPORT_CONTEXT_LOCK = threading.Lock()
_REPORT_CONTEXTS: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    """Build a stable cache key for one active report context."""
    return report_context_service.build_report_key(symbol, report)


def clear_report_context_cache() -> None:
    """Remove all cached report contexts from process memory."""
    with _REPORT_CONTEXT_LOCK:
        _REPORT_CONTEXTS.clear()


def store_report_context(report_key: str, context: dict[str, Any]) -> None:
    """Store one report context as an isolated copy in process memory."""
    with _REPORT_CONTEXT_LOCK:
        _REPORT_CONTEXTS.pop(report_key, None)
        _REPORT_CONTEXTS[report_key] = copy.deepcopy(context)
        while len(_REPORT_CONTEXTS) > REPORT_CONTEXT_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_REPORT_CONTEXTS))
            _REPORT_CONTEXTS.pop(oldest_key)


def get_cached_report_context(report_key: str) -> dict[str, Any] | None:
    """Return a copy of the cached report context for the requested key."""
    with _REPORT_CONTEXT_LOCK:
        current = _REPORT_CONTEXTS.get(report_key)
    return copy.deepcopy(current) if current else None


def _normalize_history_turn(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return one cleaned chat turn when the role and content are usable."""
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None

    content = str(item.get("content") or "").strip()
    if not content:
        return None

    normalized_turn: dict[str, Any] = {"role": role, "content": content}
    if role != "assistant":
        return normalized_turn

    raw_evidence = item.get("evidence", [])
    evidence_items: list[str] = []
    if isinstance(raw_evidence, str):
        if raw_evidence.strip():
            evidence_items.append(raw_evidence.strip())
    elif isinstance(raw_evidence, list):
        for entry in raw_evidence:
            if isinstance(entry, dict):
                text = str(entry.get("snippet") or entry.get("text") or entry.get("content") or "").strip()
            else:
                text = str(entry or "").strip()
            if text:
                evidence_items.append(text)
    cleaned_evidence = _dedupe_support_text_entries(evidence_items)
    if cleaned_evidence:
        normalized_turn["evidence"] = [item["text"] for item in cleaned_evidence]

    raw_citations = item.get("citations", [])
    citation_items: list[dict[str, Any]] = []
    if isinstance(raw_citations, dict):
        citation_items.append(raw_citations)
    elif isinstance(raw_citations, list):
        for entry in raw_citations:
            if isinstance(entry, dict):
                citation_items.append(entry)
            else:
                snippet = str(entry or "").strip()
                if snippet:
                    citation_items.append({"snippet": snippet})
    cleaned_citations = _dedupe_citation_snippets(citation_items)
    if cleaned_citations:
        normalized_turn["citations"] = cleaned_citations

    return normalized_turn


def _normalize_scope_text(*parts: object) -> str:
    """Join text fragments into a normalized lowercase scope string."""
    joined = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return re.sub(r"\s+", " ", joined).strip().lower()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Return True when the normalized text contains any configured keyword."""
    return any(keyword in text for keyword in keywords)


def _is_follow_up_without_explicit_topic(question: str) -> bool:
    """Return True when the wording looks like a follow-up but does not name a report topic."""
    normalized_question = _normalize_scope_text(question)
    if not normalized_question:
        return False
    if _contains_any(normalized_question, REPORT_SCOPE_KEYWORDS):
        return False
    if any(normalized_question.startswith(prefix) for prefix in GENERIC_FOLLOW_UP_PREFIXES):
        return True
    return _contains_any(normalized_question, REPORT_FOLLOW_UP_KEYWORDS)


def _extract_follow_up_anchor(history: list[dict[str, Any]], session_summary: str) -> str:
    """Pick the most recent substantive user topic to anchor a weak follow-up question."""
    for turn in reversed(history or []):
        if turn.get("role") != "user":
            continue
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        if not _is_follow_up_without_explicit_topic(content):
            return content

    summary_text = str(session_summary or "").strip()
    if summary_text:
        return summary_text
    return ""


def _rewrite_follow_up_question(question: str, anchor: str) -> str:
    """Rewrite a generic follow-up so the downstream answer stays anchored to the prior topic."""
    return (
        f"请基于当前年报，继续展开上一轮关于“{anchor}”的问题。"
        f"当前追问：{str(question or '').strip()}"
    )


def _build_follow_up_clarification_answer() -> dict[str, Any]:
    """Return a clarification response when a follow-up lacks any usable topic anchor."""
    return {
        "mode": "rule_fallback",
        "short_answer": (
            "This Q&A session is limited to the currently loaded annual report. "
            "Please specify which part you want to expand, such as overseas growth, ToB, risk, or cash flow."
        ),
        "evidence": [],
        "citations": [],
        "confidence": "low",
    }


def _collect_report_grounding(context: dict[str, Any]) -> list[str]:
    """Collect report-backed snippets for grounded fallback answers."""
    evidence: list[str] = []

    llm_analysis = context.get("llm_analysis")
    if isinstance(llm_analysis, dict):
        summary_text = str(llm_analysis.get("summary") or "").strip()
        if summary_text:
            evidence.append(summary_text)

    extracted_metrics = context.get("extracted_metrics")
    if isinstance(extracted_metrics, dict):
        for key in ("revenue", "net_profit", "operating_cash_flow", "deducted_net_profit", "roe", "capex_cash_outflow"):
            value = extracted_metrics.get(key)
            if value is not None:
                evidence.append(f"{key}: {value}")
            if len(evidence) >= 5:
                return evidence

    report_text = str(context.get("report_text") or "").strip()
    if report_text and len(evidence) < 5:
        evidence.append(report_text[:180])

    return evidence


def _question_requests_growth_drivers(question: str) -> bool:
    """Return whether the question is asking what drove growth or improvement."""
    normalized_question = _normalize_scope_text(question)
    if not normalized_question:
        return False
    if not any(hint in normalized_question for hint in REPORT_DRIVER_QUESTION_HINTS):
        return False
    return any(token in normalized_question for token in ("利润", "净利", "收入", "营收", "增长", "改善", "现金流"))


def _extract_reason_lines(report_text: str) -> list[str]:
    """Extract report 'reason explanation' sentences that can anchor fallback answers."""
    return [
        _normalize_support_text(match)
        for match in re.findall(r"([^\n。]*?(?:变动原因说明|原因说明)[:：][^。]*。)", str(report_text or ""))
        if _normalize_support_text(match)
    ]


def _score_reason_line(question: str, line: str) -> int:
    """Score one reason line against the active question."""
    normalized_question = _normalize_scope_text(question)
    normalized_line = _normalize_scope_text(line)
    score = 0
    if any(token in normalized_question for token in ("现金流", "回款")) and "现金流" in normalized_line:
        score += 4
    if any(token in normalized_question for token in ("真实", "为真", "利润质量")) and any(
        token in normalized_line for token in ("现金流", "现金", "销售商品收到的现金")
    ):
        score += 4
    if any(token in normalized_question for token in ("利润", "净利", "收入", "营收", "增长")) and any(
        token in normalized_line for token in ("收入", "营收", "销量", "销售价格", "产品", "利润")
    ):
        score += 3
    if "改善" in normalized_question and any(token in normalized_line for token in ("增加", "改善", "提升")):
        score += 1
    return score


def _build_reason_line_fallback(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Build a concise fallback answer from report reason lines when the question asks for drivers."""
    if not _question_requests_growth_drivers(question):
        return None

    reason_lines = _extract_reason_lines(str(context.get("report_text") or ""))
    if not reason_lines:
        return None

    ranked_lines = sorted(
        reason_lines,
        key=lambda line: (_score_reason_line(question, line), -reason_lines.index(line)),
        reverse=True,
    )
    selected_lines = [line for line in ranked_lines if _score_reason_line(question, line) > 0] or ranked_lines
    primary_line = selected_lines[0]
    primary_reason = re.split(r"[:：]", primary_line, maxsplit=1)[-1].strip().rstrip("。；;")
    evidence = list(selected_lines[:2])

    extracted_metrics = context.get("extracted_metrics") or {}
    report_year = extracted_metrics.get("report_year")
    report_period_label = f"报告期（{report_year}年）" if report_year else "报告期"
    revenue = extracted_metrics.get("revenue")
    net_profit = extracted_metrics.get("net_profit")
    if revenue is not None:
        evidence.append(f"{report_period_label}营业收入 = {_format_metric_answer_value('revenue', float(revenue))}。")
    if net_profit is not None:
        evidence.append(f"{report_period_label}净利润 = {_format_metric_answer_value('net_profit', float(net_profit))}。")

    return {
        "mode": "rule_fallback",
        "short_answer": (
            f"今年利润增长的主要支撑是{re.sub(r'^主要是', '', primary_reason).strip()}，收入端变化对利润形成了直接拉动。"
            if primary_reason
            else primary_line
        ),
        "evidence": evidence,
        "citations": [],
        "confidence": "medium",
    }


def _question_requests_cashflow_match(question: str) -> bool:
    """Return whether the question is explicitly asking about cash-flow profit matching."""
    normalized_question = _normalize_scope_text(question)
    if not normalized_question:
        return False
    if not any(token in normalized_question for token in ("现金流", "经营现金流")):
        return False
    return any(hint in normalized_question for hint in REPORT_CASHFLOW_MATCH_QUESTION_HINTS)


def _question_requests_profit_authenticity(question: str) -> bool:
    """Return whether the question asks whether reported profit is authentic / high quality."""
    normalized_question = _normalize_scope_text(question)
    if not normalized_question or "净利润" not in normalized_question:
        return False
    return any(hint in normalized_question for hint in REPORT_PROFIT_AUTHENTICITY_HINTS)


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    """Return one ratio when both numeric inputs are usable."""
    if numerator is None or denominator is None:
        return None
    denominator_float = float(denominator)
    if denominator_float == 0:
        return None
    return float(numerator) / denominator_float


def _build_profit_quality_fallback(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Build structured fallback answers for cash-flow matching and profit-authenticity questions."""
    wants_cashflow_match = _question_requests_cashflow_match(question)
    wants_profit_authenticity = _question_requests_profit_authenticity(question)
    if not wants_cashflow_match and not wants_profit_authenticity:
        return None

    extracted_metrics = context.get("extracted_metrics") or {}
    report_year = extracted_metrics.get("report_year")
    report_period_label = f"报告期（{report_year}年）" if report_year else "报告期"
    net_profit = extracted_metrics.get("net_profit")
    deducted_net_profit = extracted_metrics.get("deducted_net_profit")
    operating_cash_flow = extracted_metrics.get("operating_cash_flow")
    answers = context.get("answers") or []

    evidence: list[str] = []
    if operating_cash_flow is not None:
        evidence.append(
            f"{report_period_label}经营现金流 = {_format_metric_answer_value('operating_cash_flow', float(operating_cash_flow))}。"
        )
    if net_profit is not None:
        evidence.append(f"{report_period_label}净利润 = {_format_metric_answer_value('net_profit', float(net_profit))}。")
    if deducted_net_profit is not None:
        evidence.append(
            f"{report_period_label}扣非净利润 = {_format_metric_answer_value('deducted_net_profit', float(deducted_net_profit))}。"
        )

    cashflow_ratio = _safe_ratio(operating_cash_flow, net_profit)
    cashflow_support = _find_metric_support_line("operating_cash_flow", answers)
    if cashflow_ratio is None and cashflow_support:
        ratio_match = re.search(r"经营现金流/净利润\s*=\s*([0-9.]+)x", cashflow_support)
        if ratio_match:
            cashflow_ratio = float(ratio_match.group(1))
        evidence.append(cashflow_support)
    if cashflow_ratio is not None:
        evidence.append(f"经营现金流/净利润 = {cashflow_ratio:.2f}x。")
    if operating_cash_flow is not None and net_profit is not None:
        cashflow_gap = float(operating_cash_flow) - float(net_profit)
        evidence.append(
            f"经营现金流较净利润{'高' if cashflow_gap >= 0 else '低'}约{abs(cashflow_gap) / 100_000_000:.2f}亿元。"
        )
    elif cashflow_ratio is not None:
        evidence.append("现有线索显示经营现金流与净利润偏离不大。")
        if net_profit is not None:
            estimated_cashflow_gap = float(net_profit) * abs(cashflow_ratio - 1.0)
            evidence.append(
                f"按现有线索推算，经营现金流与净利润的差额大致在{estimated_cashflow_gap / 100_000_000:.2f}亿元以内。"
            )

    deducted_ratio = _safe_ratio(deducted_net_profit, net_profit)
    deducted_support = _find_metric_support_line("deducted_net_profit", answers)
    if deducted_ratio is None and deducted_support:
        ratio_match = re.search(r"扣非净利润/净利润\s*=\s*([0-9.]+)x", deducted_support)
        if ratio_match:
            deducted_ratio = float(ratio_match.group(1))
        evidence.append(deducted_support)
    if deducted_ratio is not None:
        evidence.append(f"扣非净利润/净利润 = {deducted_ratio:.2f}x。")
    if deducted_net_profit is not None and net_profit is not None:
        deducted_gap = float(deducted_net_profit) - float(net_profit)
        evidence.append(f"扣非净利润与净利润差额约{abs(deducted_gap) / 100_000_000:.2f}亿元。")
    elif deducted_ratio is not None:
        evidence.append("现有线索显示扣非口径与净利润偏离不大。")
        if net_profit is not None:
            estimated_deducted_gap = float(net_profit) * abs(deducted_ratio - 1.0)
            evidence.append(f"按现有线索推算，扣非净利润与净利润差额约{estimated_deducted_gap / 100_000_000:.2f}亿元。")

    reason_lines = _extract_reason_lines(str(context.get("report_text") or ""))
    ranked_lines = sorted(
        reason_lines,
        key=lambda line: (_score_reason_line(question, line), -reason_lines.index(line)),
        reverse=True,
    )
    for line in ranked_lines:
        if _score_reason_line(question, line) > 0 and any(token in line for token in ("现金流", "现金", "回款")):
            evidence.append(line)

    if wants_profit_authenticity:
        cashflow_phrase = "经营现金流与净利润基本匹配"
        if cashflow_ratio is not None:
            if cashflow_ratio >= 1.05:
                cashflow_phrase = "经营现金流高于净利润"
            elif cashflow_ratio < 0.90:
                cashflow_phrase = "经营现金流低于净利润"

        deducted_phrase = "扣非净利润与净利润差异较小"
        if deducted_ratio is not None and 0.95 <= deducted_ratio <= 1.05:
            deducted_phrase = "扣非净利润与净利润几乎一致"

        short_answer = f"净利润较为真实，主要因为{cashflow_phrase}，且{deducted_phrase}。"
    else:
        if cashflow_ratio is None:
            short_answer = "经营现金流和净利润的匹配度当前只能做定性判断，暂未稳定抽到完整结构化比值。"
        elif 0.90 <= cashflow_ratio <= 1.20:
            short_answer = f"基本匹配，经营现金流/净利润约{cashflow_ratio:.2f}x，现金兑现情况较好。"
        elif cashflow_ratio > 1.20:
            short_answer = f"匹配度偏强，经营现金流/净利润约{cashflow_ratio:.2f}x，现金回笼强于利润确认。"
        else:
            short_answer = f"匹配度偏弱，经营现金流/净利润约{cashflow_ratio:.2f}x，还需要结合回款和营运资金变化继续看。"

    return {
        "mode": "rule_fallback",
        "short_answer": short_answer,
        "evidence": evidence,
        "citations": [],
        "confidence": "medium",
    }


def _collect_prior_assistant_support_fingerprints(history: list[dict[str, Any]]) -> set[str]:
    """Collect compact fingerprints for support already shown in recent assistant turns."""
    prior_fingerprints: set[str] = set()
    for turn in history or []:
        if str(turn.get("role") or "").strip().lower() != "assistant":
            continue

        candidates: list[str] = [str(turn.get("content") or "").strip()]
        candidates.extend(str(item or "").strip() for item in turn.get("evidence") or [])
        candidates.extend(
            str(item.get("snippet") or "").strip()
            for item in turn.get("citations") or []
            if isinstance(item, dict)
        )

        for candidate in candidates:
            fingerprint = _support_text_fingerprint(candidate)
            if fingerprint:
                prior_fingerprints.add(fingerprint)

    return prior_fingerprints


def _support_text_is_already_covered(text: str, prior_fingerprints: set[str]) -> bool:
    """Return whether one support line is already covered by recent assistant output."""
    fingerprint = _support_text_fingerprint(text)
    if not fingerprint:
        return False
    return any(
        fingerprint == prior_fingerprint
        or fingerprint in prior_fingerprint
        or prior_fingerprint in fingerprint
        for prior_fingerprint in prior_fingerprints
    )


def _filter_evidence_already_covered_by_history(
    evidence: list[str],
    history: list[dict[str, Any]],
) -> list[str]:
    """Remove fallback evidence lines that repeat recent assistant support."""
    prior_fingerprints = _collect_prior_assistant_support_fingerprints(history)
    if not prior_fingerprints:
        return evidence
    return [item for item in evidence if not _support_text_is_already_covered(item, prior_fingerprints)]


def _prefer_fresh_evidence(evidence: list[str], history: list[dict[str, Any]]) -> list[str]:
    """Prefer new support lines, but keep the original set if filtering would empty the answer."""
    deduped = [item["text"] for item in _dedupe_support_text_entries(evidence)]
    filtered = _filter_evidence_already_covered_by_history(deduped, history)
    return filtered or deduped


def _filter_support_already_covered_by_history(
    *,
    short_answer: str,
    evidence: list[str],
    citations: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Remove support that merely repeats facts already surfaced in recent assistant turns."""
    prior_fingerprints = _collect_prior_assistant_support_fingerprints(history)
    if not prior_fingerprints:
        return evidence, citations

    filtered_evidence = [
        item for item in evidence if not _support_text_is_already_covered(item, prior_fingerprints)
    ]
    filtered_citations = [
        item
        for item in citations
        if not _support_text_is_already_covered(str(item.get("snippet") or "").strip(), prior_fingerprints)
    ]

    if not filtered_citations and citations and _contains_numeric_claim(short_answer):
        filtered_citations = citations

    return filtered_evidence, filtered_citations


def _normalize_llm_answer_payload(
    payload: dict[str, Any],
    *,
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Normalize provider JSON into one stable Q&A shape or reject unusable payloads."""
    short_answer = str(
        payload.get("short_answer")
        or payload.get("answer")
        or payload.get("summary")
        or payload.get("response")
        or ""
    ).strip()
    if not short_answer:
        return None

    raw_evidence = payload.get("evidence", [])
    if isinstance(raw_evidence, str):
        evidence_items = [raw_evidence.strip()] if raw_evidence.strip() else []
    elif isinstance(raw_evidence, list):
        evidence_items = [str(item).strip() for item in raw_evidence if str(item).strip()]
    else:
        evidence_items = []

    raw_citations = payload.get("citations", [])
    if isinstance(raw_citations, dict):
        citation_items = [raw_citations]
    elif isinstance(raw_citations, list):
        citation_items = [item for item in raw_citations if isinstance(item, dict)]
    else:
        citation_items = []

    cleaned_evidence = _dedupe_support_text_entries(evidence_items)
    cleaned_citations = _dedupe_citation_snippets(citation_items)
    citation_fingerprints = {
        _support_text_fingerprint(str(item.get("snippet") or "").strip())
        for item in cleaned_citations
        if str(item.get("snippet") or "").strip()
    }
    evidence = [
        item["text"]
        for item in cleaned_evidence
        if _support_text_fingerprint(item["text"]) not in citation_fingerprints
    ]
    citations = cleaned_citations
    evidence, citations = _filter_support_already_covered_by_history(
        short_answer=short_answer,
        evidence=evidence,
        citations=citations,
        history=history,
    )

    return {
        "short_answer": short_answer,
        "evidence": evidence[:5],
        "citations": citations[:5],
        "confidence": str(payload.get("confidence") or "low").strip() or "low",
}


def _normalize_support_text(text: str) -> str:
    """Collapse whitespace so support strings are stable for cleaning and comparison."""
    return re.sub(r"\s+", " ", str(text or "").strip())


def _support_text_fingerprint(text: str) -> str:
    """Build a compact fingerprint for de-duplicating support snippets."""
    normalized = _normalize_support_text(text).lower()
    return re.sub(r"[\s,，。；;:：!?！？\"'“”‘’·\\-—()（）\\[\\]{}]+", "", normalized)


def _looks_like_dense_table_row(text: str) -> bool:
    """Return whether one support string looks like a raw table row with multiple adjacent numeric columns."""
    normalized = _normalize_support_text(text)
    numeric_tokens = re.findall(r"[+-]?\d[\d,]*(?:\.\d+)?", normalized)
    if len(numeric_tokens) < 3:
        return False
    punctuation_count = len(re.findall(r"[。；;!?！？]", normalized))
    return punctuation_count == 0


def _compact_dense_table_row(text: str) -> str:
    """Compress a dense table row into one metric label plus the primary value."""
    normalized = _normalize_support_text(text)
    for label in REPORT_QA_NUMERIC_SUPPORT_LABELS:
        match = re.search(
            rf"({re.escape(label)})\s*[:：]?\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|元|%)?",
            normalized,
        )
        if match:
            compact = f"{match.group(1)}{match.group(2)}{match.group(3) or ''}"
            return compact if compact.endswith(("。", "；", ";")) else f"{compact}。"
    return normalized


def _clean_support_text(text: str) -> str:
    """Normalize one LLM evidence or citation snippet into a compact user-facing line."""
    normalized = _normalize_support_text(text)
    if not normalized:
        return ""
    if _looks_like_dense_table_row(normalized):
        normalized = _compact_dense_table_row(normalized)
    return normalized


def _format_amount_answer(value: float) -> str:
    """Format one currency amount for direct report-Q&A answers."""
    return f"{value:,.2f}元（约{value / 100_000_000:.2f}亿元）"


def _format_metric_answer_value(metric_name: str, value: float) -> str:
    """Format one structured metric value for a user-facing Q&A answer."""
    if metric_name in {"roe", "debt_ratio"}:
        return f"{value:.2f}%"
    return _format_amount_answer(value)


def _format_metric_answer_brief(metric_name: str, value: float) -> str:
    """Format one structured metric value for a concise short answer."""
    if metric_name in {"roe", "debt_ratio"}:
        return f"{value:.2f}%"
    return f"{value / 100_000_000:.2f}亿元"


def _question_requests_metric(question: str, metric_name: str) -> bool:
    """Return whether the question explicitly asks for one supported metric."""
    normalized = _normalize_scope_text(question)
    if not normalized:
        return False
    if metric_name == "deducted_net_profit":
        return any(token in normalized for token in ("扣非净利润", "扣除非经常性损益的净利润"))
    if metric_name == "net_profit":
        return any(token in normalized for token in ("归属于上市公司股东的净利润", "归母净利润")) or bool(
            re.search(r"(?<!扣非)净利润", normalized)
        )
    if metric_name == "operating_cash_flow":
        return any(token in normalized for token in ("经营活动产生的现金流量净额", "经营现金流", "经营活动现金流"))
    if metric_name == "revenue":
        return any(token in normalized for token in ("营业总收入", "营业收入", "营收"))
    if metric_name == "roe":
        return any(token in normalized for token in ("净资产收益率", "roe"))
    if metric_name == "debt_ratio":
        return "资产负债率" in normalized
    if metric_name == "capex_cash_outflow":
        return any(token in normalized for token in ("资本开支", "购建固定资产"))
    return False


def _find_metric_support_line(metric_name: str, answers: list[dict[str, Any]]) -> str | None:
    """Find one existing rule-based evidence line relevant to the requested metric."""
    keywords_by_metric = {
        "deducted_net_profit": ("扣非净利润", "扣非净利润/净利润"),
        "net_profit": ("净利润",),
        "operating_cash_flow": ("经营现金流", "现金流量净额"),
        "revenue": ("收入", "营收"),
        "roe": ("ROE", "净资产收益率"),
        "debt_ratio": ("资产负债率",),
        "capex_cash_outflow": ("资本开支",),
    }
    for answer in answers or []:
        for item in answer.get("evidence") or []:
            text = str(item or "").strip()
            if text and any(keyword in text for keyword in keywords_by_metric.get(metric_name, ())):
                return text
    return None


def _build_direct_metric_answer(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Answer direct metric questions from structured extracted metrics when available."""
    normalized_question = _normalize_scope_text(question)
    if not normalized_question or not any(token in normalized_question for token in DIRECT_METRIC_QUESTION_HINTS):
        return None

    extracted_metrics = context.get("extracted_metrics") or {}
    report_year = extracted_metrics.get("report_year")
    requested_metrics: list[tuple[str, str]] = []
    for metric_name, label in (
        ("deducted_net_profit", "扣非净利润"),
        ("net_profit", "净利润"),
        ("operating_cash_flow", "经营现金流"),
        ("revenue", "营业收入"),
        ("roe", "ROE"),
        ("debt_ratio", "资产负债率"),
        ("capex_cash_outflow", "资本开支"),
    ):
        if _question_requests_metric(question, metric_name):
            requested_metrics.append((metric_name, label))

    if not requested_metrics:
        return None

    short_parts: list[str] = []
    evidence: list[str] = []
    answers = context.get("answers") or []
    report_period_label = f"报告期（{report_year}年）" if report_year else "报告期"
    for metric_name, label in requested_metrics:
        value = extracted_metrics.get(metric_name)
        if value is not None:
            value_float = float(value)
            formatted_value = _format_metric_answer_value(metric_name, value_float)
            short_parts.append(f"{label}约{_format_metric_answer_brief(metric_name, value_float)}")
            evidence.append(f"{report_period_label}{label} = {formatted_value}。")
            continue

        support_line = _find_metric_support_line(metric_name, answers)
        if support_line:
            short_parts.append(f"{label}原值当前未稳定抽取到")
            evidence.append(f"{report_period_label}{label}补充线索：{support_line}")
        else:
            short_parts.append(f"{label}原值当前未稳定抽取到")

    if not short_parts:
        return None

    return {
        "mode": "rule_fallback",
        "short_answer": "，".join(short_parts) + "。",
        "evidence": evidence[:5],
        "citations": [],
        "confidence": "medium",
    }


def _dedupe_support_text_entries(items: list[str]) -> list[dict[str, Any]]:
    """Clean and de-duplicate one flat list of evidence-like strings."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        dense = _looks_like_dense_table_row(item)
        cleaned = _clean_support_text(item)
        if not cleaned:
            continue
        fingerprint = _support_text_fingerprint(cleaned)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append({"text": cleaned, "dense": dense})
    return out


def _dedupe_citation_snippets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean and de-duplicate citation snippets while preserving non-snippet metadata."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean_support_text(str(item.get("snippet") or "").strip())
        if not cleaned:
            continue
        fingerprint = _support_text_fingerprint(cleaned)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized_item = dict(item)
        normalized_item["snippet"] = cleaned
        out.append(normalized_item)
    return out


def _contains_numeric_claim(text: str) -> bool:
    """Return whether one answer string contains an explicit numeric claim."""
    return bool(re.search(r"\d", text))


def _payload_with_numeric_claims_requires_citations(payload: dict[str, Any]) -> bool:
    """Return whether an LLM payload mentions numeric facts without any usable citation snippet."""
    texts = [str(payload.get("short_answer") or "").strip()]
    texts.extend(str(item or "").strip() for item in payload.get("evidence", []) or [])
    has_numeric_claim = any(_contains_numeric_claim(text) for text in texts if text)
    if not has_numeric_claim:
        return False

    citations = payload.get("citations", []) or []
    return not any(str(item.get("snippet") or "").strip() for item in citations if isinstance(item, dict))


def _is_report_scoped_question(
    question: str,
    context: dict[str, Any],
    history: list[dict[str, Any]],
    session_summary: str,
) -> bool:
    """Return True when the question is about the active report and not clearly out of scope."""
    report_text = str(context.get("report_text") or "").strip()
    if not report_text:
        return False

    normalized_question = _normalize_scope_text(question)
    if not normalized_question:
        return False

    if _contains_any(normalized_question, OUT_OF_SCOPE_KEYWORDS):
        return False

    if _contains_any(normalized_question, REPORT_SCOPE_KEYWORDS):
        return True

    context_text = _normalize_scope_text(
        session_summary,
        " ".join(turn.get("content", "") for turn in history or []),
        context.get("report_text"),
        context.get("llm_analysis", {}).get("summary") if isinstance(context.get("llm_analysis"), dict) else "",
    )
    if _contains_any(context_text, REPORT_SCOPE_KEYWORDS) and _contains_any(normalized_question, REPORT_FOLLOW_UP_KEYWORDS):
        return True

    return False


def bound_history(
    history: list[dict[str, Any]],
    session_summary: str,
    *,
    max_turns: int = REPORT_QA_HISTORY_MAX_TURNS,
) -> tuple[list[dict[str, str]], str]:
    """Keep the latest raw turns and compress older turns into the carried summary."""
    normalized_history: list[dict[str, Any]] = []
    for item in history or []:
        if isinstance(item, dict):
            cleaned_turn = _normalize_history_turn(item)
            if cleaned_turn is not None:
                normalized_history.append(cleaned_turn)

    carried_summary = str(session_summary or "").strip()
    if len(normalized_history) <= max_turns:
        return normalized_history, carried_summary

    older_turns = normalized_history[:-max_turns]
    recent_turns = normalized_history[-max_turns:]
    compressed_turns = " | ".join(f'{turn["role"]}: {turn["content"][:120]}' for turn in older_turns)
    summary_parts = [carried_summary, compressed_turns]
    updated_summary = " ".join(part for part in summary_parts if part).strip()
    return recent_turns, updated_summary


def _select_rule_fallback_reference(question: str, answers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the most relevant cached answer for a constrained fallback response."""
    normalized_question = str(question or "").strip().lower()
    if not answers:
        return None

    question_tokens = [token for token in re.split(r"[\s,，。！？!?；;:/\\|]+", normalized_question) if len(token) >= 2]
    for item in answers:
        if not isinstance(item, dict):
            continue
        candidate_text = " ".join(
            str(item.get(field) or "")
            for field in ("question", "id", "summary")
        ).strip().lower()
        if not candidate_text:
            continue
        if normalized_question and (normalized_question in candidate_text or candidate_text in normalized_question):
            return item
        if question_tokens and any(token in candidate_text for token in question_tokens):
            return item
        compact_question = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", normalized_question)
        compact_candidate = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", candidate_text)
        if len(compact_question) >= 2 and len(compact_candidate) >= 2:
            question_bigrams = {compact_question[idx : idx + 2] for idx in range(len(compact_question) - 1)}
            candidate_bigrams = {compact_candidate[idx : idx + 2] for idx in range(len(compact_candidate) - 1)}
            if len(question_bigrams & candidate_bigrams) >= 2:
                return item
    return None


def build_rule_fallback_answer(question: str, context: dict[str, Any]) -> dict[str, Any]:
    """Build a constrained report-only answer from cached context without using the LLM."""
    return build_rule_fallback_answer_with_scope(question, context, allow_cached_answer=True)


def build_rule_fallback_answer_with_scope(
    question: str,
    context: dict[str, Any],
    *,
    allow_cached_answer: bool,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a boundary or report-grounded fallback answer based on the current scope."""
    direct_metric_answer = _build_direct_metric_answer(question, context) if allow_cached_answer else None
    if direct_metric_answer is not None:
        return direct_metric_answer
    reason_line_answer = _build_reason_line_fallback(question, context) if allow_cached_answer else None
    if reason_line_answer is not None:
        reason_line_answer["evidence"] = _prefer_fresh_evidence(reason_line_answer["evidence"], history or [])[:5]
        return reason_line_answer
    profit_quality_answer = _build_profit_quality_fallback(question, context) if allow_cached_answer else None
    if profit_quality_answer is not None:
        profit_quality_answer["evidence"] = _prefer_fresh_evidence(profit_quality_answer["evidence"], history or [])[:5]
        return profit_quality_answer

    answers = context.get("answers") or []
    reference_answer = _select_rule_fallback_reference(question, answers) if allow_cached_answer else None
    grounded_evidence = _collect_report_grounding(context) if allow_cached_answer else []

    evidence: list[str] = []
    if reference_answer:
        for item in reference_answer.get("evidence") or []:
            text = str(item or "").strip()
            if text:
                evidence.append(text)
    if not evidence and grounded_evidence:
        evidence.extend(grounded_evidence)
    evidence = _prefer_fresh_evidence(evidence, history or [])

    short_answer = ""
    if reference_answer:
        short_answer = str(reference_answer.get("summary") or reference_answer.get("answer") or "").strip()
    if not short_answer and grounded_evidence:
        short_answer = grounded_evidence[0]
    if not short_answer:
        short_answer = (
            "This Q&A session is limited to the currently loaded annual report. "
            "Please narrow the question to this report."
        )

    confidence = "medium" if evidence else "low"
    return {
        "mode": "rule_fallback",
        "short_answer": short_answer,
        "evidence": evidence[:5],
        "citations": [],
        "confidence": confidence,
    }


def answer_report_question(
    *,
    symbol: str,
    report_key: str,
    question: str,
    history: list[dict[str, Any]],
    session_summary: str,
    use_llm: bool,
) -> dict[str, Any]:
    """Answer one report-scoped question using cached context, bounded history, and optional LLM support."""
    context = get_cached_report_context(report_key)
    if not context:
        artifact = fetch_report_artifact(report_key)
        if artifact:
            context = report_context_service.artifact_row_to_context(artifact)
            store_report_context(report_key, context)
    if not context:
        raise ValueError("Active report context not found. Reload the report and try again.")
    if str(context.get("symbol") or "").strip() != str(symbol or "").strip():
        raise ValueError("Report key does not match the requested symbol.")

    bounded_history, updated_summary = bound_history(history, session_summary)
    question_text = str(question or "").strip()
    llm_question = question_text
    if _is_follow_up_without_explicit_topic(question_text):
        follow_up_anchor = _extract_follow_up_anchor(bounded_history, updated_summary)
        if not follow_up_anchor:
            fallback = _build_follow_up_clarification_answer()
            fallback["updated_session_summary"] = updated_summary
            fallback["session_reset"] = False
            fallback["report_key"] = report_key
            return fallback
        llm_question = _rewrite_follow_up_question(question_text, follow_up_anchor)

    is_report_scoped = _is_report_scoped_question(llm_question, context, bounded_history, updated_summary)
    if not is_report_scoped:
        fallback = build_rule_fallback_answer_with_scope(llm_question, context, allow_cached_answer=False, history=bounded_history)
        fallback["updated_session_summary"] = updated_summary
        fallback["session_reset"] = False
        fallback["report_key"] = report_key
        return fallback

    if use_llm:
        try:
            logger.info(
                "report_qa llm_attempt symbol=%s report_key=%s question=%s history_turns=%s",
                symbol,
                report_key,
                llm_question,
                len(bounded_history),
            )
            llm_answer = answer_report_question_with_llm(
                report_title=(context.get("report") or {}).get("title"),
                report_text=str(context.get("report_text") or ""),
                question=llm_question,
                history=bounded_history,
                session_summary=updated_summary,
                extracted_metrics=context.get("extracted_metrics", {}) or {},
                answers=context.get("answers", []) or [],
                llm_analysis=context.get("llm_analysis"),
            )
            if isinstance(llm_answer, dict):
                normalized_payload = _normalize_llm_answer_payload(llm_answer, history=bounded_history)
                if normalized_payload is not None:
                    if _payload_with_numeric_claims_requires_citations(normalized_payload):
                        logger.warning(
                            "report_qa numeric_llm_payload_without_citations symbol=%s report_key=%s question=%s",
                            symbol,
                            report_key,
                            llm_question,
                        )
                        normalized_payload = None
                if normalized_payload is not None:
                    normalized_payload["mode"] = "llm_hybrid"
                    normalized_payload["updated_session_summary"] = updated_summary
                    normalized_payload["session_reset"] = False
                    normalized_payload.pop("session_key", None)
                    normalized_payload["report_key"] = report_key
                    logger.info(
                        "report_qa llm_success symbol=%s report_key=%s question=%s confidence=%s evidence_count=%s citation_count=%s",
                        symbol,
                        report_key,
                        llm_question,
                        normalized_payload["confidence"],
                        len(normalized_payload["evidence"]),
                        len(normalized_payload["citations"]),
                    )
                    return normalized_payload
                logger.warning(
                    "report_qa unusable_llm_payload symbol=%s report_key=%s question=%s payload_keys=%s",
                    symbol,
                    report_key,
                    llm_question,
                    sorted(llm_answer.keys()),
                )
        except Exception:
            logger.warning(
                "report_qa llm_failed symbol=%s report_key=%s question=%s",
                symbol,
                report_key,
                llm_question,
                exc_info=True,
            )
            pass

    fallback = build_rule_fallback_answer_with_scope(llm_question, context, allow_cached_answer=True, history=bounded_history)
    fallback["updated_session_summary"] = updated_summary
    fallback["session_reset"] = False
    fallback["report_key"] = report_key
    return fallback
