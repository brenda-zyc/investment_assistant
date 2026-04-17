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


def _context_from_artifact(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the report-Q&A context shape from one persisted artifact row."""
    return report_context_service.artifact_row_to_context(row)


def _normalize_history_turn(item: dict[str, Any]) -> dict[str, str] | None:
    """Return one cleaned chat turn when the role and content are usable."""
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None

    content = str(item.get("content") or "").strip()
    if not content:
        return None

    return {"role": role, "content": content}


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


def _extract_follow_up_anchor(history: list[dict[str, str]], session_summary: str) -> str:
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


def _normalize_llm_answer_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
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
        evidence = [raw_evidence.strip()] if raw_evidence.strip() else []
    elif isinstance(raw_evidence, list):
        evidence = [str(item).strip() for item in raw_evidence if str(item).strip()]
    else:
        evidence = []

    raw_citations = payload.get("citations", [])
    if isinstance(raw_citations, dict):
        citations = [raw_citations]
    elif isinstance(raw_citations, list):
        citations = [item for item in raw_citations if isinstance(item, dict)]
    else:
        citations = []

    return {
        "short_answer": short_answer,
        "evidence": evidence[:5],
        "citations": citations[:5],
        "confidence": str(payload.get("confidence") or "low").strip() or "low",
    }


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
    history: list[dict[str, str]],
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
    normalized_history: list[dict[str, str]] = []
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
) -> dict[str, Any]:
    """Build a boundary or report-grounded fallback answer based on the current scope."""
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
            context = _context_from_artifact(artifact)
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
        fallback = build_rule_fallback_answer_with_scope(llm_question, context, allow_cached_answer=False)
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
                normalized_payload = _normalize_llm_answer_payload(llm_answer)
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

    fallback = build_rule_fallback_answer_with_scope(llm_question, context, allow_cached_answer=True)
    fallback["updated_session_summary"] = updated_summary
    fallback["session_reset"] = False
    fallback["report_key"] = report_key
    return fallback
