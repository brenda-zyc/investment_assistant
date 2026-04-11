from __future__ import annotations

import datetime as dt
import logging

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

logger = logging.getLogger(__name__)


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
    source_url: str | None,
    status_item: dict,
    default_status: str,
) -> dict:
    """Build one normalized row for industry cycle output."""
    return {
        "industry": spec["industry"],
        "indicator_key": spec["indicator_key"],
        "indicator": spec["indicator"],
        "display_name": spec.get("display_name") or spec["indicator"],
        "value": value,
        "1y_percentile": percentile_1y,
        "5y_percentile": percentile_5y,
        "as_of": as_of,
        "source": source,
        "source_url": source_url,
        "status": status_item.get("status") or default_status,
        "error": status_item.get("error"),
    }


def _industry_max_age_days(spec: dict[str, str]) -> int:
    """Return the freshness window for one industry indicator before cached data becomes stale."""
    configured = spec.get("max_age_days")
    if configured is not None:
        try:
            return int(configured)
        except (TypeError, ValueError):
            pass
    return 21


def _industry_status_for_cached_row(
    spec: dict[str, str],
    latest_date: dt.date,
    status_item: dict,
) -> dict:
    """Map refresh diagnostics onto the currently displayed cached row semantics."""
    refresh_status = str(status_item.get("status") or "").strip()
    refresh_error = status_item.get("error")
    max_age_days = _industry_max_age_days(spec)
    is_stale = latest_date < (dt.date.today() - dt.timedelta(days=max_age_days))

    if refresh_status in {"blocked", "fetch_failed", "dns_failed", "no_data"}:
        return {
            "status": "stale" if is_stale else "cached",
            "error": refresh_error,
        }
    if is_stale:
        return {
            "status": "stale",
            "error": refresh_error or f"Cached snapshot is older than {max_age_days} days.",
        }
    if refresh_status in {"unknown", ""}:
        return {}
    return status_item


def _industry_allowed_source_prefixes(spec: dict[str, str]) -> set[str]:
    """Return raw source prefixes that remain valid for the current indicator mapping."""
    prefixes: set[str] = set()
    if str(spec.get("global_symbols") or "").strip():
        prefixes.add("futures_global_hist_em")
    special_source = str(spec.get("special_source") or "").strip()
    if special_source == "sxcoal_cci5500":
        prefixes.add("sxcoal_cci5500")
    elif special_source == "cempi_index":
        prefixes.add("cempi_index")
    elif special_source == "construction_index":
        prefixes.add("macro_china_construction_price_index")
    elif special_source == "soozhu_pork":
        prefixes.update({"moa_market_info", "spot_hog_lean_price_soozhu"})
    elif special_source == "soozhu_corn":
        prefixes.add("spot_corn_price_soozhu")
    elif special_source == "moa_beef":
        prefixes.add("moa_market_info")
    if str(spec.get("sina_contract") or "").strip():
        prefixes.add("futures_zh_daily_sina")
    if str(spec.get("basis_var") or "").strip():
        prefixes.add("futures_spot_price_daily")
    return prefixes


def _industry_source_metadata(spec: dict[str, str], source: str | None) -> tuple[str | None, str | None]:
    """Return human-readable source label and upstream URL for one industry row."""
    raw_source = str(source or "").strip()
    raw_key = raw_source.split(":", 1)[0] if raw_source else ""
    if raw_key == "futures_zh_daily_sina":
        contract = raw_source.split(":", 1)[1] if ":" in raw_source else str(spec.get("sina_contract") or "")
        return "新浪财经", f"https://finance.sina.com.cn/futures/quotes/{contract}.shtml"
    if raw_key == "futures_global_hist_em":
        symbol = raw_source.split(":", 1)[1] if ":" in raw_source else str(spec.get("global_symbols") or "").split(",")[0]
        return "东方财富", f"https://quote.eastmoney.com/globalfuture/{symbol}.html?jump_to_web=true"
    if raw_key == "spot_hog_lean_price_soozhu":
        return "搜猪网", "https://www.soozhu.com/"
    if raw_key == "spot_corn_price_soozhu":
        return "搜猪网", "https://www.soozhu.com/"
    if raw_key == "moa_market_info":
        return "农业农村部", "https://www.moa.gov.cn/xw/zxfb/"
    if raw_key == "futures_spot_price_daily":
        return "100ppi", "https://www.100ppi.com/sf/"
    default_name = str(spec.get("source_name") or "").strip() or raw_source or None
    default_url = str(spec.get("source_url") or "").strip() or None
    return default_name, default_url


def _industry_source_matches_spec(spec: dict[str, str], source: str | None) -> bool:
    """Return whether a cached row source is still compatible with the current spec."""
    raw_source = str(source or "").strip()
    if not raw_source:
        return True
    allowed_prefixes = _industry_allowed_source_prefixes(spec)
    if not allowed_prefixes:
        return True
    return raw_source.split(":", 1)[0] in allowed_prefixes


def build_industry_cycles_payload(rows: list[dict], diagnostics: dict | None = None) -> dict:
    """Build current value plus 1Y/5Y percentile payload for industry indicators."""
    grouped_points: dict[str, list[tuple[dt.date, float]]] = {}
    grouped_meta: dict[str, dict[str, str]] = {}
    diagnostics = diagnostics or {}
    indicator_status_map: dict[str, dict] = diagnostics.get("indicator_status", {}) or {}
    specs = get_industry_indicator_specs()

    for row in rows:
        indicator_key = str(row.get("indicator") or "").strip()
        if not indicator_key:
            continue
        spec = next((item for item in specs if item["indicator_key"] == indicator_key), None)
        if spec is not None and not _industry_source_matches_spec(spec, row.get("source")):
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
                source=str(spec.get("source_name") or "") or None,
                source_url=str(spec.get("source_url") or "") or None,
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
        status_item = _industry_status_for_cached_row(
            spec,
            latest_date,
            indicator_status_map.get(indicator_key, {}),
        )
        source_label, source_url = _industry_source_metadata(
            spec,
            grouped_meta.get(indicator_key, {}).get("source") or None,
        )
        row_payload = _build_indicator_row(
            spec,
            value=latest_value,
            percentile_1y=p1y,
            percentile_5y=p5y,
            as_of=as_of_text,
            source=source_label,
            source_url=source_url,
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


def _external_refresh_window_specs() -> list[tuple[str, str]]:
    """Return labeled lookback windows for staged external refresh logging."""
    start_dates = _external_refresh_windows()
    return [("7d", start_dates[0]), ("30d", start_dates[1]), ("90d", start_dates[2])]


def _merge_external_refresh_diagnostics(base: dict, update: dict) -> dict:
    """Merge staged external refresh diagnostics, preserving the latest known per-indicator result."""
    base_dns = base.setdefault("dns", {})
    base_dns.update(update.get("dns") or {})
    base_status = base.setdefault("indicator_status", {})
    base_status.update(update.get("indicator_status") or {})
    return base


def _terminal_external_statuses() -> set[str]:
    """Return refresh statuses that should stop further lookback expansion in the same run."""
    return {"fetch_failed", "dns_failed"}


def _window_status_summary(indicator_status: dict[str, dict], indicator_keys: set[str]) -> dict[str, int]:
    """Count per-status outcomes for one staged external refresh window."""
    summary = {
        "ok": 0,
        "proxy": 0,
        "no_data": 0,
        "fetch_failed": 0,
        "dns_failed": 0,
        "other": 0,
    }
    for indicator_key in indicator_keys:
        status = str((indicator_status.get(indicator_key) or {}).get("status") or "other")
        if status not in summary:
            summary["other"] += 1
            continue
        summary[status] += 1
    return summary


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
        for window_label, external_start_date in _external_refresh_window_specs():
            if not pending_indicator_keys:
                break
            pending_before = set(pending_indicator_keys)
            window_rows, window_diagnostics = fetch_external_data_rows_with_diagnostics(
                start_date=external_start_date,
                indicator_keys=pending_indicator_keys,
            )
            _merge_external_refresh_diagnostics(external_runtime_diagnostics, window_diagnostics)
            resolved_indicator_keys: set[str] = set()
            terminal_failure_keys = {
                indicator_key
                for indicator_key in pending_before
                if str((window_diagnostics.get("indicator_status", {}).get(indicator_key) or {}).get("status") or "")
                in _terminal_external_statuses()
            }
            if window_rows:
                fetched_rows.extend(window_rows)
                fetched_indicator_keys = {
                    str(row.get("indicator_key") or "").strip()
                    for row in window_rows
                    if str(row.get("indicator_key") or "").strip()
                }
                pending_indicator_keys -= fetched_indicator_keys
                resolved_indicator_keys = fetched_indicator_keys
            pending_indicator_keys -= terminal_failure_keys
            status_summary = _window_status_summary(
                window_diagnostics.get("indicator_status", {}) or {},
                pending_before,
            )
            logger.info(
                "external_refresh window=%s start=%s pending=%d resolved=%d terminal_failures=%d indicators=%s",
                window_label,
                external_start_date,
                len(pending_before),
                len(resolved_indicator_keys),
                len(terminal_failure_keys),
                ",".join(sorted(resolved_indicator_keys)) or "-",
            )
            logger.info(
                "external_refresh summary window=%s ok=%d proxy=%d no_data=%d fetch_failed=%d dns_failed=%d other=%d",
                window_label,
                status_summary["ok"],
                status_summary["proxy"],
                status_summary["no_data"],
                status_summary["fetch_failed"],
                status_summary["dns_failed"],
                status_summary["other"],
            )
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
    payload["refreshed_at"] = dt.datetime.now().isoformat(timespec="seconds")
    payload["external_rows"] = build_external_data_payload(
        history_external_rows,
        diagnostics=external_runtime_diagnostics if diagnostics else None,
    )
    if not diagnostics:
        payload.pop("dns", None)
    # TODO: Expose diagnostics as a dedicated endpoint for operator-focused troubleshooting.
    payload["warnings"] = warnings
    return payload
