from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import fetch_financial_reports, get_conn, init_db, upsert_financial_reports
from app.services.financial_report_service import REPORT_EXTRACTION_VERSION, _primary_metrics_section_lines


_OFFICIAL_REPORT_HOSTS = {"static.cninfo.com.cn", "www.cninfo.com.cn"}
_AMOUNT_UNIT_MULTIPLIERS = {
    "元": 1.0,
    "千元": 1_000.0,
    "万元": 10_000.0,
    "百万元": 1_000_000.0,
    "千万元": 10_000_000.0,
    "亿元": 100_000_000.0,
    "亿": 100_000_000.0,
    "万": 10_000.0,
}
_AMOUNT_METRICS = ("revenue", "net_profit")
_MULTI_YEAR_AMOUNT_ROW_SPECS = (
    ("revenue", ("营业收入",), ("营业收入整体情况", "营业收入构成")),
    ("net_profit", ("归属于上市公司股东", "净利润"), ("扣除非经常性损益",)),
    ("total_assets", ("总资产",), ("占总资产比例", "总资产比例", "境外资产")),
    ("net_assets", ("归属于上市公司股东", "净资产"), ("净资产收益率",)),
)
_MULTI_YEAR_RATIO_ROW_SPECS = (("roe", ("加权平均净资产收益率",), ()),)
_INLINE_UNIT_RE = re.compile(r"[（(](千万元|百万元|千元|万元|亿元|亿|万|元)[）)]")
_ROW_NUMBER_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%?")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _load_report_artifacts(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()

    if symbols:
        placeholders = ", ".join("?" for _ in symbols)
        cur.execute(
            f"""
            SELECT symbol, report_key, document_url, detail_url, title, parsed_at, report_text, extracted_metrics_json
            FROM report_artifacts
            WHERE symbol IN ({placeholders})
            ORDER BY parsed_at DESC
            """,
            tuple(symbols),
        )
    else:
        cur.execute(
            """
            SELECT symbol, report_key, document_url, detail_url, title, parsed_at, report_text, extracted_metrics_json
            FROM report_artifacts
            ORDER BY parsed_at DESC
            """
        )

    rows = []
    for row in cur.fetchall():
        payload = dict(row)
        payload["extracted_metrics"] = json.loads(payload.pop("extracted_metrics_json"))
        rows.append(payload)
    conn.close()
    return rows


def _artifact_has_official_report_url(artifact: dict[str, Any]) -> bool:
    for key in ("document_url", "detail_url"):
        url = str((artifact or {}).get(key) or "").strip()
        if not url:
            continue
        hostname = (urlparse(url).hostname or "").lower()
        if hostname in _OFFICIAL_REPORT_HOSTS:
            return True
    return False


def _artifact_is_annual_candidate(artifact: dict[str, Any]) -> bool:
    extracted_metrics = (artifact or {}).get("extracted_metrics") or {}
    report_date = str(extracted_metrics.get("report_date") or "").strip()
    return (
        extracted_metrics.get("extraction_version") == REPORT_EXTRACTION_VERSION
        and report_date.endswith("-12-31")
        and _artifact_has_official_report_url(artifact)
    )


def _best_evidence_by_metric(extracted_metrics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in extracted_metrics.get("evidence") or []:
        metric = str(item.get("metric") or "").strip()
        if not metric:
            continue
        current = best.get(metric)
        current_score = float((current or {}).get("score") or float("-inf"))
        item_score = float(item.get("score") or 0.0)
        if current is None or item_score >= current_score:
            best[metric] = item
    return best


def _parse_number_and_unit(raw_number: str) -> tuple[float | None, str]:
    text = str(raw_number or "").strip()
    match = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(千万元|百万元|千元|万元|亿元|亿|万|元)?$", text)
    if not match:
        return None, ""
    value = _to_float(match.group(1))
    unit = str(match.group(2) or "").strip()
    return value, unit


def _infer_amount_unit_from_evidence(evidence: dict[str, Any]) -> str:
    explicit_unit = str(evidence.get("unit_context") or "").strip()
    if explicit_unit:
        return explicit_unit

    snippet = str(evidence.get("snippet") or "")
    inline_match = re.search(r"[（(](千万元|百万元|千元|万元|亿元|亿|万|元)[）)]", snippet)
    if inline_match:
        return str(inline_match.group(1))

    header_match = re.search(r"单位\s*[:：]\s*(千万元|百万元|千元|万元|亿元|亿|万|元)", snippet)
    if header_match:
        return str(header_match.group(1))
    return ""


def _normalized_amount_from_artifact(extracted_metrics: dict[str, Any], metric_name: str) -> float | None:
    evidence = _best_evidence_by_metric(extracted_metrics).get(metric_name)
    if evidence:
        raw_value, inline_unit = _parse_number_and_unit(str(evidence.get("raw_number") or ""))
        unit = _infer_amount_unit_from_evidence(evidence) or inline_unit
        if raw_value is not None:
            multiplier = _AMOUNT_UNIT_MULTIPLIERS.get(unit)
            if multiplier is not None:
                return raw_value * multiplier
            if not unit:
                return raw_value

    return _to_float(extracted_metrics.get(metric_name))


def _derive_debt_ratio(extracted_metrics: dict[str, Any]) -> float | None:
    debt_ratio = _to_float(extracted_metrics.get("debt_ratio"))
    if debt_ratio is not None:
        return debt_ratio

    total_assets = _to_float(extracted_metrics.get("total_assets"))
    if total_assets in (None, 0):
        return None

    total_liabilities = _to_float(extracted_metrics.get("total_liabilities"))
    if total_liabilities is not None:
        return total_liabilities / total_assets * 100

    for equity_key in ("net_assets", "attributable_equity"):
        equity = _to_float(extracted_metrics.get(equity_key))
        if equity is not None:
            return (total_assets - equity) / total_assets * 100
    return None


def _build_financial_report_row_from_artifact(artifact: dict[str, Any]) -> dict[str, Any] | None:
    extracted_metrics = (artifact or {}).get("extracted_metrics") or {}
    report_year = extracted_metrics.get("report_year")
    report_date = str(extracted_metrics.get("report_date") or "").strip()
    if report_year is None or not report_date.endswith("-12-31"):
        return None

    row = {
        "report_year": int(report_year),
        "report_date": report_date,
        "revenue": _normalized_amount_from_artifact(extracted_metrics, "revenue"),
        "net_profit": _normalized_amount_from_artifact(extracted_metrics, "net_profit"),
        "roe": _to_float(extracted_metrics.get("roe")),
        "debt_ratio": _derive_debt_ratio(extracted_metrics),
    }
    if row["revenue"] is None and row["net_profit"] is None:
        return None
    return row


def _find_primary_metric_line(
    section_lines: list[tuple[str, str | None]],
    *,
    include_tokens: tuple[str, ...],
    exclude_tokens: tuple[str, ...] = (),
) -> tuple[str, str | None] | None:
    normalized_excludes = tuple(token.replace(" ", "") for token in exclude_tokens)
    for idx, (line, section_unit) in enumerate(section_lines):
        candidate_lines: list[tuple[str, str | None]] = [(line, section_unit)]
        if idx + 1 < len(section_lines):
            next_line, next_unit = section_lines[idx + 1]
            candidate_lines.append((f"{line}{next_line}", section_unit or next_unit))

        for candidate_line, candidate_unit in candidate_lines:
            normalized = re.sub(r"\s+", "", candidate_line)
            if not all(token in normalized for token in include_tokens):
                continue
            if any(token and token in normalized for token in normalized_excludes):
                continue
            keyword_positions = [candidate_line.find(token) for token in include_tokens if candidate_line.find(token) >= 0]
            if keyword_positions:
                candidate_line = candidate_line[min(keyword_positions) :]
            return candidate_line, candidate_unit
    return None


def _line_amount_unit(line: str, fallback_unit: str | None = None) -> str:
    inline_match = _INLINE_UNIT_RE.search(line)
    if inline_match:
        return str(inline_match.group(1))
    return str(fallback_unit or "")


def _extract_year_series_values(
    line: str,
    *,
    report_year: int,
    value_type: str,
    unit_context: str | None = None,
) -> dict[int, float]:
    values: list[float] = []
    line_unit = _line_amount_unit(line, unit_context)
    multiplier = _AMOUNT_UNIT_MULTIPLIERS.get(line_unit, 1.0)

    for token in _ROW_NUMBER_RE.findall(line):
        cleaned = str(token).replace(",", "").strip()
        is_percent = cleaned.endswith("%")
        numeric_text = cleaned[:-1] if is_percent else cleaned
        value = _to_float(numeric_text)
        if value is None:
            continue
        if value_type == "amount":
            if is_percent:
                continue
            values.append(value * multiplier)
            continue
        if is_percent:
            values.append(value)

    if len(values) < 3:
        return {}
    return {
        report_year: values[0],
        report_year - 1: values[1],
        report_year - 2: values[-1],
    }


def _merge_row_payload(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"report_year", "report_date"}:
            merged[key] = value
            continue
        if merged.get(key) is None and value is not None:
            merged[key] = value
    return merged


def _extract_multi_year_financial_rows_from_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    extracted_metrics = (artifact or {}).get("extracted_metrics") or {}
    report_year = extracted_metrics.get("report_year")
    text = str((artifact or {}).get("report_text") or "")
    title = str((artifact or {}).get("title") or "").strip() or None
    if report_year is None or not text.strip():
        return []

    section_lines = _primary_metrics_section_lines(text, title=title)
    if not section_lines:
        return []

    rows_by_year: dict[int, dict[str, Any]] = {}
    asset_series: dict[int, float] = {}
    net_asset_series: dict[int, float] = {}

    for metric_name, include_tokens, exclude_tokens in _MULTI_YEAR_AMOUNT_ROW_SPECS:
        candidate = _find_primary_metric_line(
            section_lines,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
        )
        if candidate is None:
            continue
        candidate_line, candidate_unit = candidate
        for year, value in _extract_year_series_values(
            candidate_line,
            report_year=int(report_year),
            value_type="amount",
            unit_context=candidate_unit,
        ).items():
            row = rows_by_year.setdefault(year, {"report_year": year, "report_date": f"{year}-12-31"})
            if metric_name == "total_assets":
                asset_series[year] = value
            elif metric_name == "net_assets":
                net_asset_series[year] = value
            else:
                row[metric_name] = value

    for metric_name, include_tokens, exclude_tokens in _MULTI_YEAR_RATIO_ROW_SPECS:
        candidate = _find_primary_metric_line(
            section_lines,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
        )
        if candidate is None:
            continue
        candidate_line, candidate_unit = candidate
        for year, value in _extract_year_series_values(
            candidate_line,
            report_year=int(report_year),
            value_type="ratio",
            unit_context=candidate_unit,
        ).items():
            row = rows_by_year.setdefault(year, {"report_year": year, "report_date": f"{year}-12-31"})
            row[metric_name] = value

    for year, row in rows_by_year.items():
        total_assets = asset_series.get(year)
        net_assets = net_asset_series.get(year)
        if row.get("debt_ratio") is None and total_assets not in (None, 0) and net_assets is not None:
            row["debt_ratio"] = (total_assets - net_assets) / total_assets * 100

    output = [
        row
        for year, row in sorted(rows_by_year.items(), reverse=True)
        if row.get("revenue") is not None or row.get("net_profit") is not None
    ]
    return output


def _candidate_financial_rows_from_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_year: dict[int, dict[str, Any]] = {}
    for row in _extract_multi_year_financial_rows_from_artifact(artifact):
        report_year = int(row["report_year"])
        existing = rows_by_year.get(report_year)
        rows_by_year[report_year] = _merge_row_payload(existing or {}, row)

    primary_row = _build_financial_report_row_from_artifact(artifact)
    if primary_row is not None:
        report_year = int(primary_row["report_year"])
        existing = rows_by_year.get(report_year)
        rows_by_year[report_year] = _merge_row_payload(existing or {}, primary_row)

    return [rows_by_year[year] for year in sorted(rows_by_year.keys(), reverse=True)]


def _replace_cached_row(existing_rows: list[dict[str, Any]], target_row: dict[str, Any]) -> list[dict[str, Any]]:
    report_year = int(target_row["report_year"])
    updated: list[dict[str, Any]] = []
    replaced = False
    for row in existing_rows:
        if int(row.get("report_year")) == report_year:
            updated.append(dict(target_row))
            replaced = True
        else:
            updated.append(dict(row))
    if not replaced:
        updated.append(dict(target_row))
    updated.sort(key=lambda item: int(item.get("report_year") or 0), reverse=True)
    return updated


def _rows_equivalent(existing_row: dict[str, Any], target_row: dict[str, Any]) -> bool:
    if str(existing_row.get("report_date") or "") != str(target_row.get("report_date") or ""):
        return False

    for key in ("revenue", "net_profit", "roe", "debt_ratio"):
        existing_value = _to_float(existing_row.get(key))
        target_value = _to_float(target_row.get(key))
        if existing_value is None or target_value is None:
            if existing_value != target_value:
                return False
            continue
        if not math.isclose(existing_value, target_value, rel_tol=1e-9, abs_tol=1e-6):
            return False
    return True


def _needs_backfill(existing_rows: list[dict[str, Any]], target_row: dict[str, Any]) -> bool:
    report_year = int(target_row["report_year"])
    for row in existing_rows:
        if int(row.get("report_year")) != report_year:
            continue
        if not str(row.get("report_date") or "").endswith("-12-31"):
            return True
        return not _rows_equivalent(row, target_row)
    return True


def run_backfill(symbols: list[str] | None = None, *, dry_run: bool = False) -> dict[str, int]:
    init_db()
    artifacts = _load_report_artifacts(symbols)
    seen_symbol_years: set[tuple[str, int]] = set()
    existing_rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    stats = {
        "scanned": len(artifacts),
        "candidates": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_unofficial": 0,
        "invalid": 0,
    }

    for artifact in artifacts:
        if not _artifact_has_official_report_url(artifact):
            stats["skipped_unofficial"] += 1
            continue
        if not _artifact_is_annual_candidate(artifact):
            stats["invalid"] += 1
            continue

        candidate_rows = _candidate_financial_rows_from_artifact(artifact)
        if not candidate_rows:
            stats["invalid"] += 1
            continue

        symbol = str(artifact.get("symbol") or "").strip()
        existing_rows = existing_rows_by_symbol.setdefault(symbol, fetch_financial_reports(symbol))
        for row in candidate_rows:
            key = (symbol, int(row["report_year"]))
            if key in seen_symbol_years:
                continue
            seen_symbol_years.add(key)
            stats["candidates"] += 1

            if not _needs_backfill(existing_rows, row):
                stats["skipped_existing"] += 1
                continue

            if not dry_run:
                upsert_financial_reports(symbol, [row])
            existing_rows = _replace_cached_row(existing_rows, row)
            existing_rows_by_symbol[symbol] = existing_rows
            stats["updated"] += 1
            print(f"{symbol}: updated {row['report_date']}")

    return stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Backfill financial_reports from locally cached official annual report artifacts."
    )
    parser.add_argument("--symbol", action="append", default=[], help="One 6-digit A-share symbol to backfill. Repeatable.")
    parser.add_argument("--dry-run", action="store_true", help="Preview candidate rows without writing SQLite updates.")
    args = parser.parse_args(argv)

    symbols = [item.strip() for item in args.symbol if item.strip()] or None
    stats = run_backfill(symbols, dry_run=args.dry_run)
    print(
        "financial_report_backfill "
        f"scanned={stats['scanned']} candidates={stats['candidates']} updated={stats['updated']} "
        f"skipped_existing={stats['skipped_existing']} skipped_unofficial={stats['skipped_unofficial']} "
        f"invalid={stats['invalid']}"
    )


if __name__ == "__main__":
    main()
