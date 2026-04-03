from __future__ import annotations

import datetime as dt

from app.usecases import industry_usecase


def test_get_industry_cycles_skips_external_refresh_when_cache_is_fresh(monkeypatch) -> None:
    """Fresh external cache should be reused instead of triggering live refresh on every page load."""
    fresh_date = (dt.date.today() - dt.timedelta(days=2)).isoformat()

    monkeypatch.setattr(industry_usecase, "fetch_industry_prices", lambda: [])
    monkeypatch.setattr(
        industry_usecase,
        "fetch_external_data_points",
        lambda: [
            {
                "indicator_key": "usd_cnh",
                "indicator": "美元汇率（美元兑离岸人民币）",
                "trade_date": fresh_date,
                "value": 7.25,
                "source": "东方财富",
                "source_url": "https://example.com",
                "note": "cached",
            }
        ],
    )
    monkeypatch.setattr(industry_usecase, "industry_history_is_sparse", lambda _rows: False)
    monkeypatch.setattr(industry_usecase, "suggest_industry_refresh_start", lambda _rows: "20240101")
    monkeypatch.setattr(
        industry_usecase,
        "fetch_industry_price_rows_with_diagnostics",
        lambda start_date=None: ([], {}),
    )
    monkeypatch.setattr(industry_usecase, "upsert_industry_prices", lambda _rows: None)
    monkeypatch.setattr(industry_usecase, "upsert_external_data_points", lambda _rows: None)

    def fail_external_refresh(*_args, **_kwargs):
        raise AssertionError("external refresh should not run for fresh cache")

    monkeypatch.setattr(industry_usecase, "fetch_external_data_rows_with_diagnostics", fail_external_refresh)

    payload = industry_usecase.get_industry_cycles(refresh=True, diagnostics=True)

    usd_row = next(row for row in payload["external_rows"] if row["indicator_key"] == "usd_cnh")
    assert usd_row["value"] == 7.25
    assert "External data cache is fresh; skipped live refresh." not in payload["warnings"]


def test_get_industry_cycles_warns_when_external_cache_is_empty(monkeypatch) -> None:
    """Industry page should explain when external data has not been prewarmed into cache yet."""
    monkeypatch.setattr(industry_usecase, "fetch_industry_prices", lambda: [])
    monkeypatch.setattr(industry_usecase, "fetch_external_data_points", lambda: [])
    monkeypatch.setattr(industry_usecase, "industry_history_is_sparse", lambda _rows: False)
    monkeypatch.setattr(industry_usecase, "suggest_industry_refresh_start", lambda _rows: "20240101")
    monkeypatch.setattr(
        industry_usecase,
        "fetch_industry_price_rows_with_diagnostics",
        lambda start_date=None: ([], {}),
    )
    monkeypatch.setattr(industry_usecase, "upsert_industry_prices", lambda _rows: None)

    def fail_external_refresh(*_args, **_kwargs):
        raise AssertionError("external refresh should not run from the page request path")

    monkeypatch.setattr(industry_usecase, "fetch_external_data_rows_with_diagnostics", fail_external_refresh)

    payload = industry_usecase.get_industry_cycles(refresh=True, diagnostics=True)

    assert any(row["status"] == "no_data" for row in payload["external_rows"])
    assert "External data cache is empty; run scripts/update_external_data.py to populate weekly snapshots." in payload["warnings"]


def test_get_industry_cycles_can_refresh_external_without_refreshing_industry(monkeypatch) -> None:
    """External refresh button should trigger external cache refresh without rerunning industry fetch."""
    fresh_date = dt.date.today().isoformat()
    external_fetch_called = {"value": False}
    external_cache: list[dict] = []

    monkeypatch.setattr(
        industry_usecase,
        "fetch_industry_prices",
        lambda: [
            {
                "industry": "Energy",
                "indicator": "brent_oil",
                "trade_date": fresh_date,
                "value": 101.5,
                "source": "cached",
            }
        ],
    )
    monkeypatch.setattr(industry_usecase, "fetch_external_data_points", lambda: list(external_cache))
    monkeypatch.setattr(industry_usecase, "upsert_industry_prices", lambda _rows: None)
    monkeypatch.setattr(
        industry_usecase,
        "upsert_external_data_points",
        lambda rows: external_cache.extend(rows),
    )

    def fail_industry_refresh(*_args, **_kwargs):
        raise AssertionError("industry refresh should not run for external-only refresh")

    def fake_external_refresh(*_args, **_kwargs):
        external_fetch_called["value"] = True
        return (
            [
                {
                    "indicator_key": "usd_cnh",
                    "indicator": "美元汇率（美元兑离岸人民币）",
                    "trade_date": fresh_date,
                    "value": 7.2,
                    "source": "东方财富",
                    "source_url": "https://example.com",
                    "note": "fresh",
                }
            ],
            {"indicator_status": {"usd_cnh": {"status": "ok"}}},
        )

    monkeypatch.setattr(industry_usecase, "fetch_industry_price_rows_with_diagnostics", fail_industry_refresh)
    monkeypatch.setattr(industry_usecase, "fetch_external_data_rows_with_diagnostics", fake_external_refresh)

    payload = industry_usecase.get_industry_cycles(refresh=False, diagnostics=True, refresh_external=True)

    assert external_fetch_called["value"] is True
    usd_row = next(row for row in payload["external_rows"] if row["indicator_key"] == "usd_cnh")
    assert usd_row["status"] == "ok"
