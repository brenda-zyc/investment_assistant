from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core_logic import compute_financial_report_analysis, compute_financial_report_autoread_assessment
from app.db import (
    fetch_financial_reports,
    fetch_latest_report_artifact_for_symbol,
    fetch_report_artifact,
    upsert_financial_reports,
    upsert_report_artifact,
)
from app.services.financial_report_service import (
    build_autoread_llm_excerpt,
    extract_report_assessment_metrics,
    extract_financial_row_from_report_text,
    fetch_report_text_from_url,
    find_latest_annual_report,
)
from app.services.report_qa_service import build_report_key, store_report_context
from app.services.report_qa_service import answer_report_question as answer_report_question_service
from app.services.llm_service import get_effective_llm_config, interpret_annual_report_text
from app.services.market_data_service import (
    fetch_financial_summary,
    fetch_report_assessment_context,
    fetch_stock_names,
)


logger = logging.getLogger(__name__)


def get_financial_report_analysis(symbol: str, *, refresh: bool = False) -> dict:
    """Return normalized annual financial reports and auto-generated analysis insights."""
    warnings: list[str] = []
    stored_financial_rows = fetch_financial_reports(symbol)
    if refresh or not stored_financial_rows:
        try:
            financial_rows = fetch_financial_summary(symbol)
            upsert_financial_reports(symbol, financial_rows)
            stored_financial_rows = fetch_financial_reports(symbol)
        except Exception as exc:
            if stored_financial_rows:
                warnings.append(f"Financial fetch failed; returned cached data. Reason: {exc}")
            else:
                warnings.append(
                    f"Financial fetch failed; no cache available. Returned empty financial data. Reason: {exc}"
                )
                stored_financial_rows = []

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([symbol]).get(symbol) or None
    except Exception as exc:
        warnings.append(f"Stock name fetch failed. Reason: {exc}")

    analysis_payload = compute_financial_report_analysis(stored_financial_rows)
    analysis_payload["symbol"] = symbol
    analysis_payload["symbol_name"] = symbol_name
    analysis_payload["warnings"] = warnings
    # TODO: Add optional compare-years parameter for custom analysis windows.
    return analysis_payload


def analyze_financial_report_url(
    url: str,
    symbol: str | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    """Analyze a Chinese financial report link and return extracted metrics."""
    report_stub = {"document_url": url, "detail_url": None}
    report_key = build_report_key(symbol, report_stub) if symbol else None
    if report_key and not force_refresh:
        artifact_row = fetch_report_artifact(report_key)
        if artifact_row:
            _store_hot_report_context_from_artifact(artifact_row)
            return _restore_url_analysis_payload_from_artifact(artifact_row)

    fetched = fetch_report_text_from_url(url)

    extracted = extract_financial_row_from_report_text(fetched["text"], title=fetched.get("title"))
    analysis_payload = _build_url_analysis_payload(extracted)

    if extracted.get("warnings"):
        analysis_payload["highlights"] = [
            {
                "level": "warn",
                "title": "Parsing notes",
                "detail": " | ".join(extracted["warnings"]),
            },
            *analysis_payload.get("highlights", []),
        ]
    if fetched.get("tls_insecure"):
        # API assumption: insecure TLS mode is explicit operator override and should be surfaced.
        analysis_payload["highlights"] = [
            {
                "level": "warn",
                "title": "TLS warning",
                "detail": "TLS verification was bypassed via REPORT_URL_INSECURE_SSL=1. Use only in trusted networks.",
            },
            *analysis_payload.get("highlights", []),
        ]

    report_key = _persist_report_artifact(
        symbol=symbol,
        report={
            "document_url": fetched["url"],
            "detail_url": None,
            "title": fetched.get("title"),
            "content_type": fetched.get("content_type"),
            "published_at": None,
            "pdf_pages": fetched.get("pdf_pages"),
        },
        report_text=fetched.get("text"),
        extracted_metrics=extracted,
        answers=[],
        llm_analysis=None,
    )
    return {
        "source_url": fetched["url"],
        "source_title": fetched.get("title"),
        "content_type": fetched.get("content_type"),
        "pdf_pages": fetched.get("pdf_pages"),
        "tls_insecure": fetched.get("tls_insecure"),
        "report_key": report_key,
        "analysis": analysis_payload,
        "extracted": extracted,
    }


def answer_financial_report_question(
    *,
    symbol: str,
    report_key: str,
    question: str,
    history: list[dict[str, str]],
    session_summary: str,
    use_llm: bool,
) -> dict:
    """Validate one report-scoped question and delegate to the report-Q&A service."""
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is required")

    normalized_report_key = str(report_key or "").strip()
    if not normalized_report_key:
        raise ValueError("report_key is required")

    return answer_report_question_service(
        symbol=symbol,
        report_key=normalized_report_key,
        question=normalized_question,
        history=history,
        session_summary=session_summary,
        use_llm=use_llm,
    )


def _latest_as_of_date(
    extracted_metrics: dict | None,
    historical_context: dict[str, list[tuple[str, float]]] | None,
) -> str | None:
    """Return the latest available as-of date across extracted and historical data."""
    candidates: list[str] = []
    report_date = extracted_metrics.get("report_date") if extracted_metrics else None
    if report_date:
        candidates.append(str(report_date))
    for points in (historical_context or {}).values():
        if points:
            candidates.append(str(points[-1][0]))
    return max(candidates) if candidates else None


def _has_usable_report_metrics(extracted_metrics: dict | None) -> bool:
    """Return whether the fetched report text yielded at least one usable core metric."""
    if not extracted_metrics:
        return False
    for key in (
        "revenue",
        "net_profit",
        "roe",
        "deducted_net_profit",
        "operating_cash_flow",
        "capex_cash_outflow",
    ):
        if extracted_metrics.get(key) is not None:
            return True
    return False


def _build_url_analysis_rows(extracted_metrics: dict | None) -> list[dict[str, Any]]:
    """Convert one extracted report payload into analysis rows when a report year is known."""
    extracted_metrics = extracted_metrics or {}
    report_year = extracted_metrics.get("report_year")
    report_date = extracted_metrics.get("report_date")

    if report_year is None and report_date:
        report_year = int(str(report_date)[:4])
    if report_year is None:
        extracted_metrics["warnings"] = [
            *extracted_metrics.get("warnings", []),
            "Report year could not be verified from the document; skipped trend scoring.",
        ]
        return []
    if not report_date:
        report_date = f"{report_year}-12-31"

    return [
        {
            "report_year": report_year,
            "report_date": report_date,
            "revenue": extracted_metrics.get("revenue"),
            "net_profit": extracted_metrics.get("net_profit"),
            "roe": extracted_metrics.get("roe"),
            "debt_ratio": extracted_metrics.get("debt_ratio"),
        }
    ]


def _build_url_analysis_payload(extracted_metrics: dict | None) -> dict:
    """Build a report-analysis payload from extracted metrics."""
    analysis_payload = compute_financial_report_analysis(_build_url_analysis_rows(extracted_metrics))
    return analysis_payload


def _report_context_from_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the in-memory Q&A context shape from one persisted artifact row."""
    return {
        "symbol": row.get("symbol"),
        "report": {
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "detail_url": row.get("detail_url"),
            "document_url": row.get("document_url"),
            "content_type": row.get("content_type"),
            "pdf_pages": row.get("pdf_pages"),
        },
        "report_text": row.get("report_text"),
        "extracted_metrics": row.get("extracted_metrics") or {},
        "answers": row.get("answers") or [],
        "llm_analysis": row.get("llm_analysis"),
    }


def _artifact_row(
    *,
    symbol: str | None,
    report: dict | None,
    report_text: str | None,
    extracted_metrics: dict | None,
    answers: list[dict] | None,
    llm_analysis: dict | None,
) -> dict[str, Any] | None:
    """Build one SQLite artifact row from the current report context."""
    if not symbol or not report_text:
        return None

    report_key = build_report_key(symbol, report)
    if not report_key:
        return None

    return {
        "report_key": report_key,
        "symbol": symbol,
        "document_url": (report or {}).get("document_url"),
        "detail_url": (report or {}).get("detail_url"),
        "title": (report or {}).get("title"),
        "published_at": (report or {}).get("published_at"),
        "content_type": (report or {}).get("content_type"),
        "pdf_pages": (report or {}).get("pdf_pages"),
        "report_text": report_text,
        "extracted_metrics": extracted_metrics or {},
        "answers": answers or [],
        "llm_analysis": llm_analysis,
        "current_mode": "report_text_extracted" if _has_usable_report_metrics(extracted_metrics) else "historical_fallback",
        "parsed_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def _store_hot_report_context_from_artifact(row: dict[str, Any]) -> None:
    """Populate the optional in-memory hot cache from a persisted artifact."""
    report_key = str(row.get("report_key") or "").strip()
    if not report_key:
        return
    store_report_context(report_key, _report_context_from_artifact_row(row))


def _persist_report_artifact(
    *,
    symbol: str | None,
    report: dict | None,
    report_text: str | None,
    extracted_metrics: dict | None,
    answers: list[dict] | None,
    llm_analysis: dict | None,
) -> str | None:
    """Persist one report artifact and refresh the hot in-memory cache."""
    row = _artifact_row(
        symbol=symbol,
        report=report,
        report_text=report_text,
        extracted_metrics=extracted_metrics,
        answers=answers,
        llm_analysis=llm_analysis,
    )
    if not row:
        return None

    upsert_report_artifact(row)
    _store_hot_report_context_from_artifact(row)
    report_key = str(row["report_key"])
    return report_key


def _restore_url_analysis_payload_from_artifact(row: dict[str, Any]) -> dict:
    """Rebuild the URL-analysis response from a persisted artifact row."""
    return {
        "source_url": row.get("document_url"),
        "source_title": row.get("title"),
        "content_type": row.get("content_type"),
        "pdf_pages": row.get("pdf_pages"),
        "tls_insecure": None,
        "report_key": row.get("report_key"),
        "analysis": _build_url_analysis_payload(row.get("extracted_metrics") or {}),
        "extracted": row.get("extracted_metrics") or {},
    }


def _restore_autoread_payload_from_artifact(
    row: dict[str, Any],
    *,
    symbol_name: str | None,
    historical_context: dict[str, list[tuple[str, float]]],
    warnings: list[str],
    llm_config: dict[str, Any] | None,
) -> dict:
    """Rebuild the autoread response from a persisted artifact row."""
    stored_metrics = row.get("extracted_metrics") or {}
    assessment = compute_financial_report_autoread_assessment(stored_metrics, historical_context)
    stored_answers = row.get("answers") or assessment.get("answers", [])
    llm_analysis = row.get("llm_analysis")
    return {
        "symbol": row.get("symbol"),
        "symbol_name": symbol_name,
        "analysis_mode": "rule_based",
        "current_mode": row.get("current_mode") or "report_text_extracted",
        "report_key": row.get("report_key"),
        "llm_enabled": bool(llm_config),
        "llm_used": llm_analysis is not None,
        "llm_provider": llm_config.get("provider") if llm_config else None,
        "llm_model": llm_config.get("model") if llm_config else None,
        "llm_analysis": llm_analysis,
        "as_of": _latest_as_of_date(stored_metrics, historical_context),
        "report": {
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "detail_url": row.get("detail_url"),
            "document_url": row.get("document_url"),
            "content_type": row.get("content_type"),
            "pdf_pages": row.get("pdf_pages"),
            "tls_insecure": None,
        },
        "extracted_metrics": stored_metrics,
        "historical_context": historical_context,
        "answers": stored_answers,
        "derived_metrics": assessment.get("derived_metrics", {}),
        "warnings": warnings,
    }


def autonomous_financial_report_read(symbol: str, *, force_refresh: bool = False) -> dict:
    """Autonomously locate and analyze the latest annual report for a stock symbol."""
    warnings: list[str] = []

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([symbol]).get(symbol) or None
    except Exception as exc:
        warnings.append(f"Stock name fetch failed. Reason: {exc}")

    historical_context: dict[str, list[tuple[str, float]]] = {}
    try:
        historical_context = fetch_report_assessment_context(symbol)
    except Exception as exc:
        warnings.append(f"Historical report context fetch failed. Reason: {exc}")

    llm_config = get_effective_llm_config()
    if not force_refresh:
        latest_artifact = fetch_latest_report_artifact_for_symbol(symbol)
        if latest_artifact:
            _store_hot_report_context_from_artifact(latest_artifact)
            return _restore_autoread_payload_from_artifact(
                latest_artifact,
                symbol_name=symbol_name,
                historical_context=historical_context,
                warnings=warnings,
                llm_config=llm_config,
            )

    report_meta: dict | None = None
    fetched_report: dict | None = None
    extracted_metrics: dict | None = None
    try:
        report_meta = find_latest_annual_report(symbol)
    except Exception as exc:
        warnings.append(f"Annual report discovery failed. Reason: {exc}")

    if report_meta:
        target_url = report_meta.get("document_url") or report_meta.get("detail_url")
        try:
            fetched_report = fetch_report_text_from_url(target_url)
            extracted_metrics = extract_report_assessment_metrics(
                fetched_report["text"],
                title=(report_meta or {}).get("title") or fetched_report.get("title"),
            )
            warnings.extend(extracted_metrics.get("warnings", []))
        except Exception as exc:
            warnings.append(f"Annual report fetch or parse failed. Reason: {exc}")

    assessment = compute_financial_report_autoread_assessment(extracted_metrics, historical_context)
    current_mode = "report_text_extracted" if _has_usable_report_metrics(extracted_metrics) else "historical_fallback"
    llm_used = False
    llm_analysis: dict | None = None
    if fetched_report and fetched_report.get("text") and llm_config:
        try:
            llm_excerpt = build_autoread_llm_excerpt(
                fetched_report["text"],
                title=(report_meta or {}).get("title"),
            )
            logger.info(
                "report_autoread llm_attempt symbol=%s mode=%s report_title=%s text_length=%s excerpt_length=%s",
                symbol,
                current_mode,
                (report_meta or {}).get("title"),
                len(str(fetched_report.get("text") or "")),
                len(llm_excerpt),
            )
            llm_analysis = interpret_annual_report_text(
                symbol=symbol,
                symbol_name=symbol_name,
                report_title=(report_meta or {}).get("title"),
                report_text=llm_excerpt,
                current_mode=current_mode,
            )
            llm_used = True
            logger.info(
                "report_autoread llm_success symbol=%s mode=%s summary_present=%s note_count=%s",
                symbol,
                current_mode,
                bool(str((llm_analysis or {}).get("summary") or "").strip()),
                len((llm_analysis or {}).get("question_notes", []) or []),
            )
        except Exception as exc:
            logger.warning(
                "report_autoread llm_failed symbol=%s mode=%s reason=%s",
                symbol,
                current_mode,
                exc,
            )
            warnings.append(f"LLM interpretation failed. Reason: {exc}")
    # TODO: Add optional LLM synthesis when a model provider is configured in this repo.
    report_key = _persist_report_artifact(
        symbol=symbol,
        report={
            **(report_meta or {}),
            "content_type": fetched_report.get("content_type") if fetched_report else None,
            "pdf_pages": fetched_report.get("pdf_pages") if fetched_report else None,
        }
        if report_meta or fetched_report
        else report_meta,
        report_text=fetched_report.get("text") if fetched_report else None,
        extracted_metrics=extracted_metrics,
        answers=assessment.get("answers", []),
        llm_analysis=llm_analysis,
    )
    return {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "analysis_mode": "rule_based",
        "current_mode": current_mode,
        "report_key": report_key,
        "llm_enabled": bool(llm_config),
        "llm_used": llm_used,
        "llm_provider": llm_config.get("provider") if llm_config else None,
        "llm_model": llm_config.get("model") if llm_config else None,
        "llm_analysis": llm_analysis,
        "as_of": _latest_as_of_date(extracted_metrics, historical_context),
        "report": {
            "title": report_meta.get("title") if report_meta else None,
            "published_at": report_meta.get("published_at") if report_meta else None,
            "detail_url": report_meta.get("detail_url") if report_meta else None,
            "document_url": report_meta.get("document_url") if report_meta else None,
            "content_type": fetched_report.get("content_type") if fetched_report else None,
            "pdf_pages": fetched_report.get("pdf_pages") if fetched_report else None,
            "tls_insecure": fetched_report.get("tls_insecure") if fetched_report else None,
        },
        "extracted_metrics": extracted_metrics or {},
        "historical_context": historical_context,
        "answers": assessment.get("answers", []),
        "derived_metrics": assessment.get("derived_metrics", {}),
        "warnings": warnings,
    }
