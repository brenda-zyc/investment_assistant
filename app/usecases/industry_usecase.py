from __future__ import annotations

import datetime as dt

from app.core_logic import to_float
from app.db import fetch_industry_prices, upsert_industry_prices
from app.services.industry_data_service import (
    fetch_industry_price_rows_with_diagnostics,
    get_industry_indicator_specs,
)


def _parse_iso_date(value: object) -> dt.date | None:
    """Parse ISO-like date text to date object and return None on invalid input."""
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _compute_window_percentile(
    points: list[tuple[dt.date, float]],
    latest_date: dt.date,
    latest_value: float,
    window_days: int,
) -> tuple[int | None, int]:
    """Compute percentile of latest value inside a lookback window."""
    window_start = latest_date - dt.timedelta(days=window_days)
    window_values = [value for date_value, value in points if date_value >= window_start]
    if not window_values:
        return None, 0
    # Percentile calculation: rank latest point against values in the same lookback window.
    rank_le = sum(1 for value in window_values if value <= latest_value)
    percentile = int(round((rank_le / len(window_values)) * 100))
    return max(0, min(100, percentile)), len(window_values)


def _build_indicator_row(
    spec: dict[str, str],
    *,
    value: float | None,
    percentile_1y: int | None,
    percentile_5y: int | None,
    as_of: str | None,
    source: str | None,
    status_item: dict,
    default_status: str,
) -> dict:
    """Build one normalized row for industry cycle output."""
    return {
        "industry": spec["industry"],
        "indicator": spec["indicator"],
        "value": value,
        "1y_percentile": percentile_1y,
        "5y_percentile": percentile_5y,
        "as_of": as_of,
        "source": source,
        "status": status_item.get("status") or default_status,
        "error": status_item.get("error"),
    }


def build_industry_cycles_payload(rows: list[dict], diagnostics: dict | None = None) -> dict:
    """Build current value plus 1Y/5Y percentile payload for industry indicators."""
    grouped_points: dict[str, list[tuple[dt.date, float]]] = {}
    grouped_meta: dict[str, dict[str, str]] = {}
    diagnostics = diagnostics or {}
    indicator_status_map: dict[str, dict] = diagnostics.get("indicator_status", {}) or {}

    for row in rows:
        indicator_key = str(row.get("indicator") or "").strip()
        if not indicator_key:
            continue
        trade_date = _parse_iso_date(row.get("trade_date"))
        value = to_float(row.get("value"))
        # Data cleaning rule: skip malformed date/value rows before percentile calculations.
        if trade_date is None or value is None:
            continue
        grouped_points.setdefault(indicator_key, []).append((trade_date, value))
        grouped_meta[indicator_key] = {
            "industry": str(row.get("industry") or ""),
            "source": str(row.get("source") or ""),
        }

    for key in grouped_points:
        grouped_points[key].sort(key=lambda item: item[0])

    output_rows: list[dict] = []
    grouped_output_rows: dict[str, list[dict]] = {}
    as_of_candidates: list[str] = []
    specs = get_industry_indicator_specs()

    for spec in specs:
        indicator_key = spec["indicator_key"]
        points = grouped_points.get(indicator_key, [])
        if not points:
            status_item = indicator_status_map.get(indicator_key, {})
            row_payload = _build_indicator_row(
                spec,
                value=None,
                percentile_1y=None,
                percentile_5y=None,
                as_of=None,
                source=None,
                status_item=status_item,
                default_status="no_data",
            )
            output_rows.append(row_payload)
            grouped_output_rows.setdefault(spec["industry"], []).append(row_payload)
            continue

        latest_date, latest_value = points[-1]
        p1y, _ = _compute_window_percentile(points, latest_date, latest_value, window_days=365)
        p5y, _ = _compute_window_percentile(points, latest_date, latest_value, window_days=365 * 5)
        as_of_text = latest_date.isoformat()
        as_of_candidates.append(as_of_text)
        status_item = indicator_status_map.get(indicator_key, {})
        row_payload = _build_indicator_row(
            spec,
            value=latest_value,
            percentile_1y=p1y,
            percentile_5y=p5y,
            as_of=as_of_text,
            source=grouped_meta.get(indicator_key, {}).get("source") or None,
            status_item=status_item,
            default_status="ok",
        )
        output_rows.append(row_payload)
        grouped_output_rows.setdefault(spec["industry"], []).append(row_payload)

    industry_groups: list[dict] = []
    seen_industries: set[str] = set()
    for spec in specs:
        industry = spec["industry"]
        if industry in seen_industries:
            continue
        seen_industries.add(industry)
        industry_groups.append(
            {
                "industry": industry,
                "rows": grouped_output_rows.get(industry, []),
            }
        )

    return {
        "as_of": max(as_of_candidates) if as_of_candidates else None,
        "rows": output_rows,
        "groups": industry_groups,
        "dns": diagnostics.get("dns") or {},
    }


def suggest_industry_refresh_start(rows: list[dict]) -> str:
    """Suggest bounded incremental refresh start date to keep API latency predictable."""
    parsed_dates = [_parse_iso_date(row.get("trade_date")) for row in rows]
    valid_dates = [date_value for date_value in parsed_dates if date_value is not None]
    if not valid_dates:
        return (dt.date.today() - dt.timedelta(days=120)).strftime("%Y%m%d")
    return (max(valid_dates) - dt.timedelta(days=30)).strftime("%Y%m%d")


def industry_history_is_sparse(rows: list[dict], min_points_per_indicator: int = 12) -> bool:
    """Return True when one or more indicators have too few cached points."""
    counts: dict[str, int] = {}
    for row in rows:
        indicator = str(row.get("indicator") or "").strip()
        if not indicator:
            continue
        value = to_float(row.get("value"))
        if value is None:
            continue
        counts[indicator] = counts.get(indicator, 0) + 1

    specs = get_industry_indicator_specs()
    for spec in specs:
        indicator_key = spec["indicator_key"]
        if counts.get(indicator_key, 0) < min_points_per_indicator:
            return True
    return False


def get_industry_cycles(refresh: bool = True, diagnostics: bool = True) -> dict:
    """Return industry cycle dashboard rows with current value and 1Y/5Y percentiles."""
    warnings: list[str] = []
    runtime_diagnostics: dict = {}
    existing_rows = fetch_industry_prices()

    if refresh:
        try:
            # API assumption: upstream sources can fail; cached rows remain valid fallback.
            if industry_history_is_sparse(existing_rows):
                # Financial logic: sparse history needs longer backfill to restore indicator continuity.
                start_date = (dt.date.today() - dt.timedelta(days=365 * 3)).strftime("%Y%m%d")
                warnings.append("Industry cache sparse; triggered extended backfill window.")
            else:
                start_date = suggest_industry_refresh_start(existing_rows)

            fetched_rows, runtime_diagnostics = fetch_industry_price_rows_with_diagnostics(start_date=start_date)
            if fetched_rows:
                upsert_industry_prices(fetched_rows)
            else:
                warnings.append("Industry data fetch returned 0 rows; using existing cache.")
        except Exception as exc:
            warnings.append(f"Industry data fetch failed; using existing cache. Reason: {exc}")

    history_rows = fetch_industry_prices()
    payload = build_industry_cycles_payload(
        history_rows,
        diagnostics=runtime_diagnostics if diagnostics else None,
    )
    if not diagnostics:
        payload.pop("dns", None)
    # TODO: Expose diagnostics as a dedicated endpoint for operator-focused troubleshooting.
    payload["warnings"] = warnings
    return payload
