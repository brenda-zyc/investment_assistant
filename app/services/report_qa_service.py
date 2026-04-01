from __future__ import annotations

import copy
import re
import threading
from typing import Any

from app.services.llm_service import answer_report_question_with_llm


REPORT_CONTEXT_CACHE_MAX_ENTRIES = 8
REPORT_QA_HISTORY_MAX_TURNS = 6
_REPORT_CONTEXT_LOCK = threading.Lock()
_REPORT_CONTEXTS: dict[str, dict[str, Any]] = {}


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    """Build a stable cache key for one active report context."""
    symbol_text = str(symbol or "").strip()
    if not symbol_text or not report:
        return None

    source_url = report.get("document_url") or report.get("detail_url")
    source_text = str(source_url or "").strip()
    if not source_text:
        return None
    return f"{symbol_text}|{source_text}"


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


def _normalize_history_turn(item: dict[str, Any]) -> dict[str, str] | None:
    """Return one cleaned chat turn when the role and content are usable."""
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None

    content = str(item.get("content") or "").strip()
    if not content:
        return None

    return {"role": role, "content": content}


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
    answers = context.get("answers") or []
    llm_analysis = context.get("llm_analysis") or {}
    extracted_metrics = context.get("extracted_metrics") or {}
    reference_answer = _select_rule_fallback_reference(question, answers)
    has_reference_answer = reference_answer is not None

    evidence: list[str] = []
    if reference_answer:
        for item in reference_answer.get("evidence") or []:
            text = str(item or "").strip()
            if text:
                evidence.append(text)

    if not evidence and isinstance(llm_analysis, dict):
        summary_text = str(llm_analysis.get("summary") or "").strip()
        if summary_text:
            evidence.append(summary_text)

    if not evidence:
        for key in ("revenue", "net_profit", "operating_cash_flow", "deducted_net_profit", "roe", "capex_cash_outflow"):
            value = extracted_metrics.get(key)
            if value is not None:
                evidence.append(f"{key}: {value}")
            if len(evidence) >= 5:
                break

    if not evidence:
        report_text = str(context.get("report_text") or "").strip()
        if report_text:
            evidence.append(report_text[:180])

    short_answer = ""
    if has_reference_answer:
        short_answer = str(reference_answer.get("summary") or reference_answer.get("answer") or "").strip()
        if not short_answer and isinstance(llm_analysis, dict):
            short_answer = str(llm_analysis.get("summary") or "").strip()
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
        raise ValueError("Active report context not found. Reload the report and try again.")
    if str(context.get("symbol") or "").strip() != str(symbol or "").strip():
        raise ValueError("Report key does not match the requested symbol.")

    bounded_history, updated_summary = bound_history(history, session_summary)
    has_report_scope_match = _select_rule_fallback_reference(question, context.get("answers", []) or []) is not None
    if not has_report_scope_match:
        fallback = build_rule_fallback_answer(question, context)
        fallback["updated_session_summary"] = updated_summary
        fallback["session_reset"] = False
        fallback["session_key"] = report_key
        return fallback

    if use_llm:
        try:
            llm_answer = answer_report_question_with_llm(
                report_title=(context.get("report") or {}).get("title"),
                report_text=str(context.get("report_text") or ""),
                question=question,
                history=bounded_history,
                session_summary=updated_summary,
                extracted_metrics=context.get("extracted_metrics", {}) or {},
                answers=context.get("answers", []) or [],
                llm_analysis=context.get("llm_analysis"),
            )
            if isinstance(llm_answer, dict):
                payload = dict(llm_answer)
                payload.setdefault("short_answer", "")
                payload.setdefault("evidence", [])
                payload.setdefault("citations", [])
                payload.setdefault("confidence", "low")
                payload["mode"] = "llm_hybrid"
                payload["updated_session_summary"] = updated_summary
                payload["session_reset"] = False
                payload["session_key"] = report_key
                return payload
        except Exception:
            pass

    fallback = build_rule_fallback_answer(question, context)
    fallback["updated_session_summary"] = updated_summary
    fallback["session_reset"] = False
    fallback["session_key"] = report_key
    return fallback
