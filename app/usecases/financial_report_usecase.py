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
    REPORT_EXTRACTION_VERSION,
    build_autoread_llm_excerpt,
    extract_report_assessment_metrics,
    extract_financial_row_from_report_text,
    fetch_report_text_from_url,
    find_latest_annual_report,
)
from app.services import report_context_service
from app.services.report_qa_service import answer_report_question as answer_report_question_service
from app.services.report_qa_service import store_report_context
from app.services.llm_service import get_effective_llm_config, interpret_annual_report_text
from app.services.market_data_service import (
    fetch_financial_summary,
    fetch_report_assessment_context,
    fetch_stock_names,
)


logger = logging.getLogger(__name__)


_SNAPSHOT_DISPLAY_UNITS = {
    "amount": "CNY",
    "percent_point": "percent",
    "ratio": "percent",
}


def _report_date_is_year_end(report_date: Any) -> bool:
    """Return whether one normalized report date represents a year-end annual period."""
    return str(report_date or "").strip().endswith("-12-31")


def _select_load_report_rows(financial_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer year-end annual rows for the Load Financial Report summary path."""
    year_end_rows = [row for row in financial_rows if _report_date_is_year_end(row.get("report_date"))]
    return year_end_rows or financial_rows


def _has_year_end_financial_rows(financial_rows: list[dict[str, Any]]) -> bool:
    """Return whether cached financial rows already contain at least one year-end report period."""
    return any(_report_date_is_year_end(row.get("report_date")) for row in financial_rows)


def _latest_context_value(
    historical_context: dict[str, list[tuple[str, float]]] | None,
    key: str,
) -> float | None:
    """Return the latest historical point for one metric key when available."""
    points = (historical_context or {}).get(key) or []
    if not points:
        return None
    return points[-1][1]


def _snapshot_item(
    key: str,
    label: str,
    value: Any,
    value_type: str,
    *,
    origin: str | None = None,
    formula: str | None = None,
) -> dict[str, Any]:
    """Build one report-snapshot item with explicit availability status."""
    payload = {
        "key": key,
        "label": label,
        "value": value,
        "value_type": value_type,
        "status": "available" if value is not None else "missing",
        "origin": origin if value is not None else "missing",
        "display_unit": _SNAPSHOT_DISPLAY_UNITS.get(value_type),
    }
    if formula:
        payload["formula"] = formula
    return payload


def _build_report_snapshot(
    *,
    metrics: dict[str, Any] | None = None,
    derived_metrics: dict[str, Any] | None = None,
    historical_context: dict[str, list[tuple[str, float]]] | None = None,
) -> dict[str, Any]:
    """Build one stable report snapshot for UI cards, tables, and future exports."""
    metrics = metrics or {}
    derived_metrics = derived_metrics or {}
    metric_values = dict(metrics)
    metric_origins: dict[str, str] = {}
    for key, value in metric_values.items():
        if value is not None:
            metric_origins[key] = "derived" if key == "interest_bearing_debt" else "extracted"

    for key in ("debt_ratio",):
        if metric_values.get(key) is None:
            fallback_value = _latest_context_value(historical_context, key)
            if fallback_value is not None:
                metric_values[key] = fallback_value
                metric_origins[key] = "context_fallback"

    derived_values = dict(derived_metrics)
    derived_origins: dict[str, str] = {}
    for key, value in derived_values.items():
        if value is not None:
            derived_origins[key] = "derived"
    if derived_values.get("latest_net_margin") is None:
        revenue = metric_values.get("revenue")
        net_profit = metric_values.get("net_profit")
        if revenue not in (None, 0) and net_profit is not None:
            derived_values["latest_net_margin"] = net_profit / revenue
            derived_origins["latest_net_margin"] = "derived"

    sections = [
        {
            "id": "summary",
            "title": "Report Summary",
            "items": [
                _snapshot_item("revenue", "Revenue", metric_values.get("revenue"), "amount", origin=metric_origins.get("revenue")),
                _snapshot_item("net_profit", "Net Profit", metric_values.get("net_profit"), "amount", origin=metric_origins.get("net_profit")),
                _snapshot_item(
                    "deducted_net_profit",
                    "Deducted Net Profit",
                    metric_values.get("deducted_net_profit"),
                    "amount",
                    origin=metric_origins.get("deducted_net_profit"),
                ),
                _snapshot_item("roe", "ROE", metric_values.get("roe"), "percent_point", origin=metric_origins.get("roe")),
                _snapshot_item("revenue_yoy", "Revenue YoY", derived_values.get("revenue_yoy"), "ratio", origin=derived_origins.get("revenue_yoy")),
                _snapshot_item(
                    "net_profit_yoy",
                    "Net Profit YoY",
                    derived_values.get("net_profit_yoy"),
                    "ratio",
                    origin=derived_origins.get("net_profit_yoy"),
                ),
                _snapshot_item(
                    "latest_net_margin",
                    "Net Margin",
                    derived_values.get("latest_net_margin"),
                    "ratio",
                    origin=derived_origins.get("latest_net_margin"),
                ),
            ],
        },
        {
            "id": "balance_sheet",
            "title": "Balance Sheet Skeleton",
            "items": [
                _snapshot_item("total_assets", "Total Assets", metric_values.get("total_assets"), "amount", origin=metric_origins.get("total_assets")),
                _snapshot_item(
                    "total_liabilities",
                    "Total Liabilities",
                    metric_values.get("total_liabilities"),
                    "amount",
                    origin=metric_origins.get("total_liabilities"),
                ),
                _snapshot_item("net_assets", "Net Assets", metric_values.get("net_assets"), "amount", origin=metric_origins.get("net_assets")),
                _snapshot_item(
                    "attributable_equity",
                    "Attributable Equity",
                    metric_values.get("attributable_equity"),
                    "amount",
                    origin=metric_origins.get("attributable_equity"),
                ),
                _snapshot_item(
                    "debt_ratio",
                    "Debt Ratio",
                    metric_values.get("debt_ratio"),
                    "percent_point",
                    origin=metric_origins.get("debt_ratio"),
                ),
            ],
        },
        {
            "id": "cash_flow",
            "title": "Cash Flow & Capex",
            "items": [
                _snapshot_item(
                    "operating_cash_flow",
                    "Operating Cash Flow",
                    metric_values.get("operating_cash_flow"),
                    "amount",
                    origin=metric_origins.get("operating_cash_flow"),
                ),
                _snapshot_item(
                    "capex_cash_outflow",
                    "Capex Cash Outflow",
                    metric_values.get("capex_cash_outflow"),
                    "amount",
                    origin=metric_origins.get("capex_cash_outflow"),
                ),
            ],
        },
        {
            "id": "detail_metrics",
            "title": "Key Balance Sheet Details",
            "items": [
                _snapshot_item(
                    "monetary_funds",
                    "Monetary Funds",
                    metric_values.get("monetary_funds"),
                    "amount",
                    origin=metric_origins.get("monetary_funds"),
                ),
                _snapshot_item(
                    "accounts_receivable",
                    "Accounts Receivable",
                    metric_values.get("accounts_receivable"),
                    "amount",
                    origin=metric_origins.get("accounts_receivable"),
                ),
                _snapshot_item("inventory", "Inventory", metric_values.get("inventory"), "amount", origin=metric_origins.get("inventory")),
                _snapshot_item(
                    "fixed_assets",
                    "Fixed Assets",
                    metric_values.get("fixed_assets"),
                    "amount",
                    origin=metric_origins.get("fixed_assets"),
                ),
                _snapshot_item(
                    "construction_in_progress",
                    "Construction in Progress",
                    metric_values.get("construction_in_progress"),
                    "amount",
                    origin=metric_origins.get("construction_in_progress"),
                ),
                _snapshot_item(
                    "interest_bearing_debt",
                    "Interest-bearing Debt",
                    metric_values.get("interest_bearing_debt"),
                    "amount",
                    origin=metric_origins.get("interest_bearing_debt"),
                    formula="short_term_borrowings + current_non_current_debt + long_term_borrowings + bonds_payable + lease_liabilities",
                ),
                _snapshot_item("goodwill", "Goodwill", metric_values.get("goodwill"), "amount", origin=metric_origins.get("goodwill")),
            ],
        },
    ]
    total_count = sum(len(section["items"]) for section in sections)
    available_count = sum(1 for section in sections for item in section["items"] if item["status"] == "available")
    return {
        "sections": sections,
        "available_count": available_count,
        "total_count": total_count,
    }


def _artifact_has_current_extraction_version(row: dict[str, Any] | None) -> bool:
    """Return whether a persisted artifact was produced by the current parser rules."""
    extracted_metrics = (row or {}).get("extracted_metrics") or {}
    return extracted_metrics.get("extraction_version") == REPORT_EXTRACTION_VERSION


def _artifact_is_eligible_for_autoread_reuse(row: dict[str, Any] | None) -> bool:
    """Return whether a cached artifact is safe to reuse as the stock's active annual report."""
    if not row or not _artifact_has_current_extraction_version(row):
        return False
    return bool(str((row or {}).get("detail_url") or "").strip())


def get_financial_report_analysis(symbol: str, *, refresh: bool = False) -> dict:
    """Return normalized annual financial reports and auto-generated analysis insights."""
    warnings: list[str] = []
    stored_financial_rows = fetch_financial_reports(symbol)
    if refresh or not stored_financial_rows or not _has_year_end_financial_rows(stored_financial_rows):
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

    analysis_payload = compute_financial_report_analysis(_select_load_report_rows(stored_financial_rows))
    analysis_payload["report_snapshot"] = _build_report_snapshot(
        metrics={
            "revenue": analysis_payload["metrics"].get("revenue"),
            "net_profit": analysis_payload["metrics"].get("net_profit"),
            "roe": analysis_payload["metrics"].get("roe"),
            "debt_ratio": analysis_payload["metrics"].get("debt_ratio"),
        },
        derived_metrics=analysis_payload.get("metrics"),
    )
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
    report_key = report_context_service.build_report_key(symbol, report_stub) if symbol else None
    if report_key and not force_refresh:
        artifact_row = fetch_report_artifact(report_key)
        if artifact_row and _artifact_has_current_extraction_version(artifact_row):
            _store_hot_report_context_from_artifact(artifact_row)
            return _restore_url_analysis_payload_from_artifact(artifact_row)
        if artifact_row:
            logger.info("Refreshing stale report artifact for %s due to extraction-version mismatch.", report_key)

    fetched = fetch_report_text_from_url(url)

    extracted = extract_report_assessment_metrics(fetched["text"], title=fetched.get("title"))
    historical_context: dict[str, list[tuple[str, float]]] = {}
    if symbol:
        try:
            historical_context = fetch_report_assessment_context(symbol)
        except Exception as exc:
            logger.warning("URL report context fetch failed for %s: %s", symbol, exc)
    analysis_payload = _build_url_analysis_payload(extracted, historical_context)

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
        "report_snapshot": analysis_payload.get("report_snapshot"),
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


def _autoread_as_of_date(
    extracted_metrics: dict | None,
    historical_context: dict[str, list[tuple[str, float]]] | None,
) -> str | None:
    """Return the active report's as-of date, falling back to historical context only when needed."""
    report_date = (extracted_metrics or {}).get("report_date")
    if report_date:
        return str(report_date)
    return _latest_as_of_date(extracted_metrics, historical_context)


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


def _build_url_analysis_payload(
    extracted_metrics: dict | None,
    historical_context: dict[str, list[tuple[str, float]]] | None = None,
) -> dict:
    """Build a report-analysis payload from extracted metrics."""
    analysis_payload = compute_financial_report_analysis(_build_url_analysis_rows(extracted_metrics))
    analysis_payload["report_snapshot"] = _build_report_snapshot(
        metrics=extracted_metrics or {},
        derived_metrics=analysis_payload.get("metrics"),
        historical_context=historical_context,
    )
    return analysis_payload

def _store_hot_report_context_from_artifact(row: dict[str, Any]) -> None:
    """Populate the optional in-memory hot cache from a persisted artifact."""
    report_key = str(row.get("report_key") or "").strip()
    if not report_key:
        return
    store_report_context(report_key, report_context_service.artifact_row_to_context(row))


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
    row = report_context_service.context_to_artifact_row(
        symbol=symbol,
        report=report,
        report_text=report_text,
        extracted_metrics=extracted_metrics,
        answers=answers,
        llm_analysis=llm_analysis,
        extraction_version=REPORT_EXTRACTION_VERSION,
        is_historical_fallback=not _has_usable_report_metrics(extracted_metrics),
        now=dt.datetime.now(dt.UTC),
    )
    if not row:
        return None

    upsert_report_artifact(row)
    _store_hot_report_context_from_artifact(row)
    report_key = str(row["report_key"])
    return report_key


def _restore_url_analysis_payload_from_artifact(row: dict[str, Any]) -> dict:
    """Rebuild the URL-analysis response from a persisted artifact row."""
    historical_context: dict[str, list[tuple[str, float]]] = {}
    symbol = str(row.get("symbol") or "").strip()
    if symbol:
        try:
            historical_context = fetch_report_assessment_context(symbol)
        except Exception as exc:
            logger.warning("Artifact report context fetch failed for %s: %s", symbol, exc)
    analysis_payload = _build_url_analysis_payload(row.get("extracted_metrics") or {}, historical_context)
    return {
        "source_url": row.get("document_url"),
        "source_title": row.get("title"),
        "content_type": row.get("content_type"),
        "pdf_pages": row.get("pdf_pages"),
        "tls_insecure": None,
        "report_key": row.get("report_key"),
        "analysis": analysis_payload,
        "report_snapshot": analysis_payload.get("report_snapshot"),
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
        "as_of": _autoread_as_of_date(stored_metrics, historical_context),
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
        "report_snapshot": _build_report_snapshot(
            metrics=stored_metrics,
            derived_metrics=assessment.get("derived_metrics", {}),
            historical_context=historical_context,
        ),
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
        if latest_artifact and _artifact_is_eligible_for_autoread_reuse(latest_artifact):
            _store_hot_report_context_from_artifact(latest_artifact)
            return _restore_autoread_payload_from_artifact(
                latest_artifact,
                symbol_name=symbol_name,
                historical_context=historical_context,
                warnings=warnings,
                llm_config=llm_config,
            )
        if latest_artifact:
            if _artifact_has_current_extraction_version(latest_artifact):
                logger.info(
                    "Ignoring latest report artifact for %s because it lacks disclosure metadata and likely came from manual URL analysis.",
                    symbol,
                )
            else:
                logger.info(
                    "Refreshing stale latest report artifact for %s due to extraction-version mismatch.",
                    symbol,
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
        "as_of": _autoread_as_of_date(extracted_metrics, historical_context),
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
        "report_snapshot": _build_report_snapshot(
            metrics=extracted_metrics or {},
            derived_metrics=assessment.get("derived_metrics", {}),
            historical_context=historical_context,
        ),
        "historical_context": historical_context,
        "answers": assessment.get("answers", []),
        "derived_metrics": assessment.get("derived_metrics", {}),
        "warnings": warnings,
    }
