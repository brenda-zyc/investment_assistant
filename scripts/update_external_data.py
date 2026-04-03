from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import init_db, upsert_external_data_points
from app.services.industry_data_service import fetch_external_data_rows_with_diagnostics


def main() -> None:
    """Refresh cached external indicator data for the industry-side reference module."""
    init_db()
    start_date = (dt.date.today() - dt.timedelta(days=400)).strftime("%Y%m%d")
    rows, diagnostics = fetch_external_data_rows_with_diagnostics(start_date=start_date)
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
