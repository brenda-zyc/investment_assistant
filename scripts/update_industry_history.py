from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import init_db, upsert_industry_prices
from app.services.industry_data_service import get_industry_indicator_specs
from app.services.industry_data_service import fetch_industry_price_rows_with_diagnostics


def _history_backfill_start() -> str:
    """Return the bounded five-year backfill start date for industry history refresh."""
    return (dt.date.today() - dt.timedelta(days=365 * 5)).strftime("%Y%m%d")


def main() -> None:
    """Backfill industry indicator history into SQLite for percentile calculations."""
    init_db()
    start_date = _history_backfill_start()
    rows, diagnostics = fetch_industry_price_rows_with_diagnostics(start_date=start_date, end_date=None)
    upsert_industry_prices(rows)

    status_map = diagnostics.get("indicator_status", {}) or {}
    total_indicators = len(status_map) or len(get_industry_indicator_specs())
    ok_count = sum(1 for item in status_map.values() if item.get("status") == "ok")
    print(f"industry_history start={start_date} rows={len(rows)} indicators_ok={ok_count}/{total_indicators}")
    for indicator_key, item in status_map.items():
        status = item.get("status") or "unknown"
        source = item.get("source") or "-"
        error = item.get("error") or "-"
        print(f"{indicator_key}: status={status} source={source} error={error}")


if __name__ == "__main__":
    main()
