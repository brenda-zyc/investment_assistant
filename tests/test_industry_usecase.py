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


def test_build_external_data_payload_keeps_cached_source_and_date_when_refresh_fails() -> None:
    """Displayed source and date should continue to describe the cached value during refresh fallback."""
    rows = [
        {
            "indicator_key": "usd_cnh",
            "indicator": "美元汇率（美元兑离岸人民币）",
            "trade_date": "2026-04-02",
            "value": 6.8952,
            "source": "东方财富",
            "source_url": "https://example.com/usdcnh",
            "note": "直接抓取美元兑离岸人民币历史行情最新值。",
        }
    ]
    diagnostics = {
        "indicator_status": {
            "usd_cnh": {
                "status": "fetch_failed",
                "error": "connection aborted",
            }
        }
    }

    payload = industry_usecase.build_external_data_payload(rows, diagnostics=diagnostics)

    usd_row = next(row for row in payload if row["indicator_key"] == "usd_cnh")
    assert usd_row["value"] == 6.8952
    assert usd_row["as_of"] == "2026-04-02"
    assert usd_row["source"] == "东方财富"
    assert usd_row["status"] == "cached"
    assert "Showing cached snapshot" in usd_row["note"]
    assert usd_row["error"] == "connection aborted"


def test_build_external_data_payload_uses_cached_status_when_refresh_returns_no_new_rows() -> None:
    """Cached rows should not be relabeled as no_data when a refresh returns zero new points."""
    rows = [
        {
            "indicator_key": "comex_gold",
            "indicator": "金价（COMEX黄金）",
            "trade_date": "2026-04-02",
            "value": 4669.4,
            "source": "东方财富",
            "source_url": "https://example.com/gold",
            "note": "直接抓取 COMEX 黄金历史行情最新值。",
        }
    ]
    diagnostics = {
        "indicator_status": {
            "comex_gold": {
                "status": "no_data",
                "error": None,
            }
        }
    }

    payload = industry_usecase.build_external_data_payload(rows, diagnostics=diagnostics)

    gold_row = next(row for row in payload if row["indicator_key"] == "comex_gold")
    assert gold_row["value"] == 4669.4
    assert gold_row["as_of"] == "2026-04-02"
    assert gold_row["source"] == "东方财富"
    assert gold_row["status"] == "cached"
    assert "latest refresh returned no new data" in gold_row["note"]


def test_build_external_data_payload_keeps_no_data_when_cache_is_empty() -> None:
    """Indicators with no cached row should continue to surface no_data."""
    diagnostics = {
        "indicator_status": {
            "gold_td": {
                "status": "no_data",
                "error": None,
            }
        }
    }

    payload = industry_usecase.build_external_data_payload([], diagnostics=diagnostics)

    gold_td_row = next(row for row in payload if row["indicator_key"] == "gold_td")
    assert gold_td_row["value"] is None
    assert gold_td_row["as_of"] is None
    assert gold_td_row["source"] == "上海黄金交易所"
    assert gold_td_row["status"] == "no_data"


def test_build_industry_cycles_payload_exposes_indicator_key_and_display_name() -> None:
    rows = [
        {
            "industry": "Energy",
            "indicator": "thermal_coal_index",
            "trade_date": "2026-04-09",
            "value": 762.0,
            "source": "sxcoal_cci5500",
        }
    ]

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics={})
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")

    assert thermal_row["display_name"] == "动力煤价格指数（CCI5500）"


def test_build_industry_cycles_payload_exposes_source_link_for_index_rows() -> None:
    """Industry payload should carry human-readable source labels and upstream links."""
    rows = [
        {
            "industry": "Energy",
            "indicator": "thermal_coal_index",
            "trade_date": "2026-04-09",
            "value": 762.0,
            "source": "sxcoal_cci5500",
        },
        {
            "industry": "Steel & Construction",
            "indicator": "cement_price_index",
            "trade_date": "2026-04-08",
            "value": 101.2,
            "source": "cempi_index",
        },
    ]

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics={})
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")
    cement_row = next(row for row in payload["rows"] if row["indicator_key"] == "cement_price_index")

    assert thermal_row["source"] == "Sxcoal"
    assert thermal_row["source_url"] == "https://www.sxcoal.com/"
    assert cement_row["source"] == "水泥网"
    assert cement_row["source_url"] == "https://index.ccement.com/"


def test_build_industry_cycles_payload_marks_fresh_thermal_coal_cache_as_cached_when_source_blocked() -> None:
    """A compatible fresh cache should stay visible and be labeled cached after a blocked refresh."""
    rows = [
        {
            "industry": "Energy",
            "indicator": "thermal_coal_index",
            "trade_date": (dt.date.today() - dt.timedelta(days=2)).isoformat(),
            "value": 762.0,
            "source": "sxcoal_cci5500",
        }
    ]
    diagnostics = {
        "indicator_status": {
            "thermal_coal_index": {
                "status": "blocked",
                "error": "403 Client Error",
            }
        }
    }

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics=diagnostics)
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")

    assert thermal_row["value"] == 762.0
    assert thermal_row["status"] == "cached"


def test_build_industry_cycles_payload_marks_old_thermal_coal_cache_as_stale_when_source_blocked() -> None:
    """Blocked thermal-coal refresh with old cache should surface stale instead of blocked."""
    rows = [
        {
            "industry": "Energy",
            "indicator": "thermal_coal_index",
            "trade_date": (dt.date.today() - dt.timedelta(days=30)).isoformat(),
            "value": 762.0,
            "source": "sxcoal_cci5500",
        }
    ]
    diagnostics = {
        "indicator_status": {
            "thermal_coal_index": {
                "status": "blocked",
                "error": "403 Client Error",
            }
        }
    }

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics=diagnostics)
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")

    assert thermal_row["value"] == 762.0
    assert thermal_row["status"] == "stale"


def test_build_industry_cycles_payload_keeps_blocked_status_without_compatible_cache() -> None:
    """Blocked refresh should stay blocked when no compatible cache row exists for the new spec."""
    diagnostics = {
        "indicator_status": {
            "thermal_coal_index": {
                "status": "blocked",
                "error": "403 Client Error",
            }
        }
    }

    payload = industry_usecase.build_industry_cycles_payload([], diagnostics=diagnostics)
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")

    assert thermal_row["value"] is None
    assert thermal_row["status"] == "blocked"


def test_build_industry_cycles_payload_marks_fresh_cache_as_cached_when_refresh_fetch_fails() -> None:
    """Generic fetch failures should still present a compatible fresh cache as cached."""
    rows = [
        {
            "industry": "Steel & Construction",
            "indicator": "cement_price_index",
            "trade_date": (dt.date.today() - dt.timedelta(days=2)).isoformat(),
            "value": 101.2,
            "source": "cempi_index",
        }
    ]
    diagnostics = {
        "indicator_status": {
            "cement_price_index": {
                "status": "fetch_failed",
                "error": "RemoteDisconnected",
            }
        }
    }

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics=diagnostics)
    cement_row = next(row for row in payload["rows"] if row["indicator_key"] == "cement_price_index")

    assert cement_row["value"] == 101.2
    assert cement_row["status"] == "cached"


def test_build_industry_cycles_payload_filters_legacy_indicator_keys() -> None:
    rows = [
        {
            "industry": "Energy",
            "indicator": "thermal_coal",
            "trade_date": "2026-04-09",
            "value": 700.0,
            "source": "futures_zh_daily_sina:ZC0",
        },
        {
            "industry": "Energy",
            "indicator": "thermal_coal_index",
            "trade_date": "2026-04-09",
            "value": 762.0,
            "source": "sxcoal_cci5500",
        },
    ]

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics={})
    thermal_row = next(row for row in payload["rows"] if row["indicator_key"] == "thermal_coal_index")

    assert thermal_row["value"] == 762.0


def test_build_industry_cycles_payload_hides_legacy_source_rows_for_new_index_specs() -> None:
    rows = [
        {
            "industry": "Steel & Construction",
            "indicator": "cement_price_index",
            "trade_date": "2026-04-08",
            "value": 101.2,
            "source": "macro_china_construction_price_index",
        }
    ]

    payload = industry_usecase.build_industry_cycles_payload(rows, diagnostics={})
    cement_row = next(row for row in payload["rows"] if row["indicator_key"] == "cement_price_index")

    assert cement_row["value"] is None
    assert cement_row["status"] == "no_data"


def test_refresh_external_data_cache_uses_staged_windows_and_stops_after_first_hit(monkeypatch) -> None:
    """External refresh should probe 7/30/90-day windows and stop requesting indicators once found."""
    today = dt.date.today()
    window_7 = (today - dt.timedelta(days=7)).strftime("%Y%m%d")
    window_30 = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    window_90 = (today - dt.timedelta(days=90)).strftime("%Y%m%d")
    call_log: list[tuple[str, tuple[str, ...]]] = []
    upserted_rows: list[dict] = []

    monkeypatch.setattr(
        industry_usecase,
        "get_external_data_specs",
        lambda: [
            {"indicator_key": "usd_cnh"},
            {"indicator_key": "dollar_index"},
        ],
    )

    def fake_fetch_external_data_rows_with_diagnostics(*, start_date=None, end_date=None, indicator_keys=None):
        requested_keys = tuple(sorted(indicator_keys or []))
        call_log.append((start_date, requested_keys))
        if start_date == window_7:
            return (
                [
                    {
                        "indicator_key": "usd_cnh",
                        "indicator": "美元汇率（美元兑离岸人民币）",
                        "trade_date": today.isoformat(),
                        "value": 7.2,
                        "source": "东方财富",
                        "source_url": "https://example.com/usd",
                        "note": "fresh",
                    }
                ],
                {
                    "indicator_status": {
                        "usd_cnh": {"status": "ok", "error": None},
                        "dollar_index": {"status": "no_data", "error": None},
                    }
                },
            )
        if start_date == window_30:
            return (
                [
                    {
                        "indicator_key": "dollar_index",
                        "indicator": "美元指数",
                        "trade_date": today.isoformat(),
                        "value": 101.1,
                        "source": "东方财富",
                        "source_url": "https://example.com/dxy",
                        "note": "fresh",
                    }
                ],
                {
                    "indicator_status": {
                        "dollar_index": {"status": "ok", "error": None},
                    }
                },
            )
        raise AssertionError("refresh should stop before requesting the 90-day window")

    monkeypatch.setattr(
        industry_usecase,
        "fetch_external_data_rows_with_diagnostics",
        fake_fetch_external_data_rows_with_diagnostics,
    )
    monkeypatch.setattr(industry_usecase, "upsert_external_data_points", lambda rows: upserted_rows.extend(rows))

    diagnostics = industry_usecase._refresh_external_data_cache(existing_external_rows=[], warnings=[])

    assert call_log == [
        (window_7, ("dollar_index", "usd_cnh")),
        (window_30, ("dollar_index",)),
    ]
    assert [row["indicator_key"] for row in upserted_rows] == ["usd_cnh", "dollar_index"]
    assert diagnostics["indicator_status"]["usd_cnh"]["status"] == "ok"
    assert diagnostics["indicator_status"]["dollar_index"]["status"] == "ok"


def test_refresh_external_data_cache_falls_through_to_90_day_window(monkeypatch) -> None:
    """External refresh should keep widening the window until the latest available point is found."""
    today = dt.date.today()
    window_7 = (today - dt.timedelta(days=7)).strftime("%Y%m%d")
    window_30 = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    window_90 = (today - dt.timedelta(days=90)).strftime("%Y%m%d")
    call_log: list[str] = []
    upserted_rows: list[dict] = []

    monkeypatch.setattr(
        industry_usecase,
        "get_external_data_specs",
        lambda: [{"indicator_key": "thermal_coal_5500k"}],
    )

    def fake_fetch_external_data_rows_with_diagnostics(*, start_date=None, end_date=None, indicator_keys=None):
        call_log.append(start_date)
        if start_date in {window_7, window_30}:
            return (
                [],
                {
                    "indicator_status": {
                        "thermal_coal_5500k": {"status": "no_data", "error": None},
                    }
                },
            )
        if start_date == window_90:
            return (
                [
                    {
                        "indicator_key": "thermal_coal_5500k",
                        "indicator": "煤炭5500K：动力煤",
                        "trade_date": today.isoformat(),
                        "value": 747,
                        "source": "100ppi（代理）",
                        "source_url": "https://example.com/coal",
                        "note": "fresh",
                    }
                ],
                {
                    "indicator_status": {
                        "thermal_coal_5500k": {"status": "proxy", "error": None},
                    }
                },
            )
        raise AssertionError(f"unexpected start_date={start_date}")

    monkeypatch.setattr(
        industry_usecase,
        "fetch_external_data_rows_with_diagnostics",
        fake_fetch_external_data_rows_with_diagnostics,
    )
    monkeypatch.setattr(industry_usecase, "upsert_external_data_points", lambda rows: upserted_rows.extend(rows))

    diagnostics = industry_usecase._refresh_external_data_cache(existing_external_rows=[], warnings=[])

    assert call_log == [window_7, window_30, window_90]
    assert [row["indicator_key"] for row in upserted_rows] == ["thermal_coal_5500k"]
    assert diagnostics["indicator_status"]["thermal_coal_5500k"]["status"] == "proxy"


def test_refresh_external_data_cache_stops_retrying_fetch_failed_indicator(monkeypatch) -> None:
    """Connection-level failures should stop widening the window for the same indicator within one refresh."""
    today = dt.date.today()
    window_7 = (today - dt.timedelta(days=7)).strftime("%Y%m%d")
    window_30 = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    window_90 = (today - dt.timedelta(days=90)).strftime("%Y%m%d")
    call_log: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(
        industry_usecase,
        "get_external_data_specs",
        lambda: [
            {"indicator_key": "eur_cnh"},
            {"indicator_key": "gold_td"},
        ],
    )

    def fake_fetch_external_data_rows_with_diagnostics(*, start_date=None, end_date=None, indicator_keys=None):
        requested_keys = tuple(sorted(indicator_keys or []))
        call_log.append((start_date, requested_keys))
        if start_date == window_7:
            return (
                [],
                {
                    "indicator_status": {
                        "eur_cnh": {"status": "fetch_failed", "error": "RemoteDisconnected"},
                        "gold_td": {"status": "no_data", "error": None},
                    }
                },
            )
        if start_date == window_30:
            return (
                [],
                {
                    "indicator_status": {
                        "gold_td": {"status": "no_data", "error": None},
                    }
                },
            )
        if start_date == window_90:
            return (
                [],
                {
                    "indicator_status": {
                        "gold_td": {"status": "no_data", "error": None},
                    }
                },
            )
        raise AssertionError(f"unexpected window={start_date}")

    monkeypatch.setattr(
        industry_usecase,
        "fetch_external_data_rows_with_diagnostics",
        fake_fetch_external_data_rows_with_diagnostics,
    )
    monkeypatch.setattr(industry_usecase, "upsert_external_data_points", lambda rows: None)

    diagnostics = industry_usecase._refresh_external_data_cache(existing_external_rows=[], warnings=[])

    assert call_log == [
        (window_7, ("eur_cnh", "gold_td")),
        (window_30, ("gold_td",)),
        (window_90, ("gold_td",)),
    ]
    assert diagnostics["indicator_status"]["eur_cnh"]["status"] == "fetch_failed"
