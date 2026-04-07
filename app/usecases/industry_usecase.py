from __future__ import annotations

import datetime as dt

from app.core_logic import to_float
from app.db import (
    fetch_external_data_points,
    fetch_industry_prices,
    upsert_external_data_points,
    upsert_industry_prices,
)
from app.services.industry_data_service import (
    fetch_external_data_rows_with_diagnostics,
    fetch_industry_price_rows_with_diagnostics,
    get_external_data_specs,
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


def _external_display_status(refresh_status: str | None, has_cache: bool) -> str:
    """Map refresh diagnostics into the status shown beside the currently displayed row."""
    if not has_cache:
        return refresh_status or "no_data"
    if refresh_status in {"ok", "proxy"}:
        return refresh_status
    return "cached"


def _merge_external_display_note(
    base_note: str | None,
    refresh_status: str | None,
    has_cache: bool,
) -> str:
    """Append cache fallback context without changing the source-specific note text."""
    note = (base_note or "").strip() or "-"
    if not has_cache:
        return note
    if refresh_status == "fetch_failed":
        return f"{note} Showing cached snapshot; latest refresh failed."
    if refresh_status == "dns_failed":
        return f"{note} Showing cached snapshot; latest refresh hit DNS issues."
    if refresh_status == "no_data":
        return f"{note} Showing cached snapshot; latest refresh returned no new data."
    return note


def build_external_data_payload(rows: list[dict], diagnostics: dict | None = None) -> list[dict]:
    """Build latest-value rows for the external-data module with graceful cache diagnostics."""
    diagnostics = diagnostics or {}
    indicator_status_map: dict[str, dict] = diagnostics.get("indicator_status", {}) or {}
    grouped_points: dict[str, list[dict]] = {}

    for row in rows:
        indicator_key = str(row.get("indicator_key") or "").strip()
        if not indicator_key:
            continue
        trade_date = _parse_iso_date(row.get("trade_date"))
        value = to_float(row.get("value"))
        if trade_date is None or value is None:
            continue
        normalized = dict(row)
        normalized["_parsed_trade_date"] = trade_date
        grouped_points.setdefault(indicator_key, []).append(normalized)

    for key in grouped_points:
        grouped_points[key].sort(key=lambda item: item["_parsed_trade_date"])

    output_rows: list[dict] = []
    for spec in get_external_data_specs():
        indicator_key = spec["indicator_key"]
        status_item = indicator_status_map.get(indicator_key, {})
        refresh_status = status_item.get("status")
        refresh_error = status_item.get("error")
        points = grouped_points.get(indicator_key, [])
        if not points:
            output_rows.append(
                {
                    "indicator_key": indicator_key,
                    "indicator": spec["indicator"],
                    "value": None,
                    "as_of": None,
                    "source": spec["source"],
                    "source_url": spec["source_url"],
                    "note": _merge_external_display_note(spec["note"], refresh_status, has_cache=False),
                    "status": _external_display_status(refresh_status, has_cache=False),
                    "error": refresh_error,
                }
            )
            continue

        latest = points[-1]
        output_rows.append(
            {
                "indicator_key": indicator_key,
                "indicator": latest["indicator"],
                "value": latest["value"],
                "as_of": latest["trade_date"],
                "source": latest.get("source") or spec["source"],
                "source_url": latest.get("source_url") or spec["source_url"],
                "note": _merge_external_display_note(
                    latest.get("note") or spec["note"],
                    refresh_status,
                    has_cache=True,
                ),
                "status": _external_display_status(refresh_status, has_cache=True),
                "error": refresh_error,
            }
        )
    return output_rows


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


def external_data_is_stale(rows: list[dict], max_age_days: int = 7) -> bool:
    """Return True when external indicator cache is missing or older than the freshness window."""
    parsed_dates = [_parse_iso_date(row.get("trade_date")) for row in rows]
    valid_dates = [date_value for date_value in parsed_dates if date_value is not None]
    if not valid_dates:
        return True
    latest_date = max(valid_dates)
    return latest_date < (dt.date.today() - dt.timedelta(days=max_age_days))


def _external_refresh_windows() -> list[str]:
    """Return staged lookback windows for manual external refresh."""
    today = dt.date.today()
    return [
        (today - dt.timedelta(days=7)).strftime("%Y%m%d"),
        (today - dt.timedelta(days=30)).strftime("%Y%m%d"),
        (today - dt.timedelta(days=90)).strftime("%Y%m%d"),
    ]


def _merge_external_refresh_diagnostics(base: dict, update: dict) -> dict:
    """Merge staged external refresh diagnostics, preserving the latest known per-indicator result."""
    base_dns = base.setdefault("dns", {})
    base_dns.update(update.get("dns") or {})
    base_status = base.setdefault("indicator_status", {})
    base_status.update(update.get("indicator_status") or {})
    return base


def _refresh_external_data_cache(
    existing_external_rows: list[dict],
    warnings: list[str],
) -> dict:
    """Refresh external data cache and return runtime diagnostics for the latest fetch attempt."""
    external_runtime_diagnostics: dict = {"dns": {}, "indicator_status": {}}
    pending_indicator_keys = {
        str(spec.get("indicator_key") or "").strip()
        for spec in get_external_data_specs()
        if str(spec.get("indicator_key") or "").strip()
    }
    fetched_rows: list[dict] = []
    try:
        for external_start_date in _external_refresh_windows():
            if not pending_indicator_keys:
                break
            window_rows, window_diagnostics = fetch_external_data_rows_with_diagnostics(
                start_date=external_start_date,
                indicator_keys=pending_indicator_keys,
            )
            _merge_external_refresh_diagnostics(external_runtime_diagnostics, window_diagnostics)
            if window_rows:
                fetched_rows.extend(window_rows)
                fetched_indicator_keys = {
                    str(row.get("indicator_key") or "").strip()
                    for row in window_rows
                    if str(row.get("indicator_key") or "").strip()
                }
                pending_indicator_keys -= fetched_indicator_keys
        if fetched_rows:
            upsert_external_data_points(fetched_rows)
        elif existing_external_rows:
            warnings.append("External data refresh returned 0 rows; using existing cache.")
        else:
            warnings.append("External data fetch returned 0 rows and no cache is available yet.")
    except Exception as exc:
        if existing_external_rows:
            warnings.append(f"External data refresh failed; using existing cache. Reason: {exc}")
        else:
            warnings.append(f"External data fetch failed and no cache is available yet. Reason: {exc}")
    return external_runtime_diagnostics


def get_industry_cycles(
    refresh: bool = True,
    diagnostics: bool = True,
    refresh_external: bool = False,
) -> dict:
    """Return industry cycle dashboard rows plus cached external reference rows."""
    warnings: list[str] = []
    runtime_diagnostics: dict = {}
    external_runtime_diagnostics: dict = {}
    existing_rows = fetch_industry_prices()
    existing_external_rows = fetch_external_data_points()

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

    if refresh_external:
        external_runtime_diagnostics = _refresh_external_data_cache(existing_external_rows, warnings)
    elif existing_external_rows:
        if external_data_is_stale(existing_external_rows):
            warnings.append("External data cache is stale; showing last cached snapshot.")
    else:
        warnings.append("External data cache is empty; run scripts/update_external_data.py to populate weekly snapshots.")

    history_rows = fetch_industry_prices()
    history_external_rows = fetch_external_data_points()
    payload = build_industry_cycles_payload(
        history_rows,
        diagnostics=runtime_diagnostics if diagnostics else None,
    )
    payload["external_rows"] = build_external_data_payload(
        history_external_rows,
        diagnostics=external_runtime_diagnostics if diagnostics else None,
    )
    if not diagnostics:
        payload.pop("dns", None)
    # TODO: Expose diagnostics as a dedicated endpoint for operator-focused troubleshooting.
    payload["warnings"] = warnings
    return payload
