from __future__ import annotations

import datetime as dt

from app.core_logic import compute_financial_report_analysis
from app.db import fetch_financial_reports, upsert_financial_reports
from app.services.financial_report_service import (
    extract_financial_row_from_report_text,
    fetch_report_text_from_url,
)
from app.services.market_data_service import fetch_financial_summary, fetch_stock_names


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


def analyze_financial_report_url(url: str) -> dict:
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

    return {
        "source_url": fetched["url"],
        "source_title": fetched.get("title"),
        "content_type": fetched.get("content_type"),
        "pdf_pages": fetched.get("pdf_pages"),
        "tls_insecure": fetched.get("tls_insecure"),
        "analysis": analysis_payload,
        "extracted": extracted,
    }
