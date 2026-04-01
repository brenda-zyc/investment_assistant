from __future__ import annotations

import datetime as dt

from app.core_logic import compute_financial_report_analysis, compute_financial_report_autoread_assessment
from app.db import fetch_financial_reports, upsert_financial_reports
from app.services.financial_report_service import (
    extract_report_assessment_metrics,
    extract_financial_row_from_report_text,
    fetch_report_text_from_url,
    find_latest_annual_report,
)
from app.services.report_qa_service import build_report_key, store_report_context
from app.services.llm_service import get_effective_llm_config, interpret_annual_report_text
from app.services.market_data_service import (
    fetch_financial_summary,
    fetch_report_assessment_context,
    fetch_stock_names,
)


def get_financial_report_analysis(symbol: str) -> dict:
    """Return normalized annual financial reports and auto-generated analysis insights."""
    warnings: list[str] = []
    try:
        financial_rows = fetch_financial_summary(symbol)
        upsert_financial_reports(symbol, financial_rows)
        stored_financial_rows = fetch_financial_reports(symbol)
    except Exception as exc:
        stored_financial_rows = fetch_financial_reports(symbol)
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


def analyze_financial_report_url(url: str, symbol: str | None = None) -> dict:
    """Analyze a Chinese financial report link and return extracted metrics."""
    fetched = fetch_report_text_from_url(url)

    extracted = extract_financial_row_from_report_text(fetched["text"], title=fetched.get("title"))
    report_year = extracted.get("report_year")
    report_date = extracted.get("report_date")

    if report_year is None and report_date:
        report_year = int(str(report_date)[:4])
    if report_year is None:
        # Financial logic: fallback to current year when report-year evidence is unavailable.
        report_year = dt.date.today().year
        extracted["warnings"] = [*extracted.get("warnings", []), "Used current year as fallback report_year."]
    if not report_date:
        report_date = f"{report_year}-12-31"

    row = {
        "report_year": report_year,
        "report_date": report_date,
        "revenue": extracted.get("revenue"),
        "net_profit": extracted.get("net_profit"),
        "roe": extracted.get("roe"),
        "debt_ratio": extracted.get("debt_ratio"),
    }
    analysis_payload = compute_financial_report_analysis([row])

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

    report_key = _cache_active_report_context(
        symbol=symbol,
        report={
            "document_url": fetched["url"],
            "detail_url": None,
            "title": fetched.get("title"),
            "content_type": fetched.get("content_type"),
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


def _cache_active_report_context(
    *,
    symbol: str | None,
    report: dict | None,
    report_text: str | None,
    extracted_metrics: dict | None,
    answers: list[dict] | None,
    llm_analysis: dict | None,
) -> str | None:
    """Cache the active report context and return its report key when available."""
    if not symbol or not report_text:
        return None

    report_key = build_report_key(symbol, report)
    if not report_key:
        return None

    store_report_context(
        report_key,
        {
            "symbol": symbol,
            "report": dict(report or {}),
            "report_text": report_text,
            "extracted_metrics": extracted_metrics or {},
            "answers": answers or [],
            "llm_analysis": llm_analysis,
        },
    )
    return report_key


def autonomous_financial_report_read(symbol: str) -> dict:
    """Autonomously locate and analyze the latest annual report for a stock symbol."""
    warnings: list[str] = []

    symbol_name: str | None = None
    try:
        symbol_name = fetch_stock_names([symbol]).get(symbol) or None
    except Exception as exc:
        warnings.append(f"Stock name fetch failed. Reason: {exc}")

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

    historical_context: dict[str, list[tuple[str, float]]] = {}
    try:
        historical_context = fetch_report_assessment_context(symbol)
    except Exception as exc:
        warnings.append(f"Historical report context fetch failed. Reason: {exc}")

    assessment = compute_financial_report_autoread_assessment(extracted_metrics, historical_context)
    current_mode = "report_text_extracted" if _has_usable_report_metrics(extracted_metrics) else "historical_fallback"
    llm_config = get_effective_llm_config()
    llm_used = False
    llm_analysis: dict | None = None
    if fetched_report and fetched_report.get("text") and llm_config:
        try:
            llm_analysis = interpret_annual_report_text(
                symbol=symbol,
                symbol_name=symbol_name,
                report_title=(report_meta or {}).get("title"),
                report_text=fetched_report["text"],
                current_mode=current_mode,
            )
            llm_used = True
        except Exception as exc:
            warnings.append(f"LLM interpretation failed. Reason: {exc}")
    # TODO: Add optional LLM synthesis when a model provider is configured in this repo.
    report_key = _cache_active_report_context(
        symbol=symbol,
        report=report_meta,
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
