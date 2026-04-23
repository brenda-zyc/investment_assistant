from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import init_db, upsert_external_data_points
from app.services.industry_data_service import (
    fetch_external_data_rows_with_diagnostics,
    get_external_data_specs,
)


def _external_refresh_windows() -> list[str]:
    """Return staged lookback windows for external data refresh."""
    today = dt.date.today()
    return [
        (today - dt.timedelta(days=7)).strftime("%Y%m%d"),
        (today - dt.timedelta(days=30)).strftime("%Y%m%d"),
        (today - dt.timedelta(days=90)).strftime("%Y%m%d"),
    ]


def _merge_refresh_diagnostics(base: dict, update: dict) -> dict:
    """Merge staged refresh diagnostics into one final operator-facing summary."""
    base_dns = base.setdefault("dns", {})
    base_dns.update(update.get("dns") or {})
    base_status = base.setdefault("indicator_status", {})
    base_status.update(update.get("indicator_status") or {})
    return base


def _terminal_statuses() -> set[str]:
    """Return per-indicator refresh statuses that should stop later window retries."""
    return {"fetch_failed", "dns_failed"}


def _window_status_summary(indicator_status: dict[str, dict], indicator_keys: set[str]) -> dict[str, int]:
    """Count staged refresh outcomes for the requested indicator keys."""
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


def _refresh_external_rows_staged() -> tuple[list[dict], dict]:
    """Fetch external rows with 7/30/90-day windows and stop per indicator once a value is found."""
    pending_indicator_keys = {
        str(spec.get("indicator_key") or "").strip()
        for spec in get_external_data_specs()
        if str(spec.get("indicator_key") or "").strip()
    }
    all_rows: list[dict] = []
    diagnostics: dict = {"dns": {}, "indicator_status": {}}

    for window_days, start_date in zip((7, 30, 90), _external_refresh_windows(), strict=True):
        if not pending_indicator_keys:
            break
        pending_before = set(pending_indicator_keys)
        window_rows, window_diagnostics = fetch_external_data_rows_with_diagnostics(
            start_date=start_date,
            indicator_keys=pending_indicator_keys,
        )
        _merge_refresh_diagnostics(diagnostics, window_diagnostics)
        resolved_keys: set[str] = set()
        terminal_failure_keys = {
            indicator_key
            for indicator_key in pending_before
            if str((window_diagnostics.get("indicator_status", {}).get(indicator_key) or {}).get("status") or "")
            in _terminal_statuses()
        }
        if not window_rows:
            print(
                f"external_data window={window_days}d start={start_date} "
                f"pending={len(pending_before)} resolved=0"
            )
            pending_indicator_keys -= terminal_failure_keys
            summary = _window_status_summary(window_diagnostics.get("indicator_status", {}) or {}, pending_before)
            print(
                f"external_data summary window={window_days}d "
                f"ok={summary['ok']} proxy={summary['proxy']} no_data={summary['no_data']} "
                f"fetch_failed={summary['fetch_failed']} dns_failed={summary['dns_failed']}"
            )
            continue
        all_rows.extend(window_rows)
        fetched_keys = {
            str(row.get("indicator_key") or "").strip()
            for row in window_rows
            if str(row.get("indicator_key") or "").strip()
        }
        resolved_keys = fetched_keys
        pending_indicator_keys -= fetched_keys
        pending_indicator_keys -= terminal_failure_keys
        print(
            f"external_data window={window_days}d start={start_date} "
            f"pending={len(pending_before)} resolved={len(resolved_keys)}"
        )
        summary = _window_status_summary(window_diagnostics.get("indicator_status", {}) or {}, pending_before)
        print(
            f"external_data summary window={window_days}d "
            f"ok={summary['ok']} proxy={summary['proxy']} no_data={summary['no_data']} "
            f"fetch_failed={summary['fetch_failed']} dns_failed={summary['dns_failed']}"
        )
    return all_rows, diagnostics


def main() -> None:
    """Refresh cached external indicator data for the industry-side reference module."""
    init_db()
    rows, diagnostics = _refresh_external_rows_staged()
    upsert_external_data_points(rows)

    status_map = diagnostics.get("indicator_status", {}) or {}
    ok_count = sum(1 for item in status_map.values() if item.get("status") in {"ok", "proxy"})
    print(f"external_data rows={len(rows)} indicators_ok={ok_count}/{len(status_map)}")
    for indicator_key, item in status_map.items():
        status = item.get("status") or "unknown"
        source = item.get("source") or "-"
        error = item.get("error") or "-"
        print(f"{indicator_key}: status={status} source={source} error={error}")


if __name__ == "__main__":
    main()
