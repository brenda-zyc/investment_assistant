from __future__ import annotations

import datetime as dt
import importlib


update_industry_history = importlib.import_module("scripts.update_industry_history")


def test_update_industry_history_backfills_cached_rows(monkeypatch, capsys) -> None:
    """Industry history script should fetch a bounded backfill window and persist returned rows."""
    today = dt.date.today()
    expected_start = (today - dt.timedelta(days=365 * 5)).strftime("%Y%m%d")
    upserted_rows: list[dict] = []

    monkeypatch.setattr(update_industry_history, "init_db", lambda: None)

    def fake_fetch_industry_price_rows_with_diagnostics(*, start_date=None, end_date=None):
        assert start_date == expected_start
        assert end_date is None
        return (
            [
                {
                    "industry": "Agriculture",
                    "indicator": "beef_price",
                    "trade_date": today.isoformat(),
                    "value": 60.2,
                    "source": "moa_market_info",
                }
            ],
            {
                "indicator_status": {
                    "beef_price": {"status": "ok", "source": "moa_market_info", "error": None},
                }
            },
        )

    monkeypatch.setattr(
        update_industry_history,
        "fetch_industry_price_rows_with_diagnostics",
        fake_fetch_industry_price_rows_with_diagnostics,
    )
    monkeypatch.setattr(update_industry_history, "upsert_industry_prices", lambda rows: upserted_rows.extend(rows))

    update_industry_history.main()

    assert [row["indicator"] for row in upserted_rows] == ["beef_price"]
    output = capsys.readouterr().out
    assert f"industry_history start={expected_start} rows=1 indicators_ok=1/1" in output
    assert "beef_price: status=ok source=moa_market_info error=-" in output
