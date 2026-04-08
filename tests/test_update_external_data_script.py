from __future__ import annotations

import datetime as dt
import importlib


update_external_data = importlib.import_module("scripts.update_external_data")


def test_script_refreshes_external_data_with_staged_windows(monkeypatch, capsys) -> None:
    """Script should probe 7/30/90-day windows and stop when every indicator has fresh rows."""
    today = dt.date.today()
    window_7 = (today - dt.timedelta(days=7)).strftime("%Y%m%d")
    window_30 = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    window_90 = (today - dt.timedelta(days=90)).strftime("%Y%m%d")
    call_log: list[tuple[str, tuple[str, ...]]] = []
    upserted_rows: list[dict] = []

    monkeypatch.setattr(update_external_data, "init_db", lambda: None)
    monkeypatch.setattr(
        update_external_data,
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
                        "usd_cnh": {"status": "ok", "source": "forex_hist_em:USDCNH", "error": None},
                        "dollar_index": {"status": "no_data", "source": None, "error": None},
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
                        "dollar_index": {"status": "ok", "source": "index_global_hist_em:.DXY", "error": None},
                    }
                },
            )
        raise AssertionError("script should stop before requesting the 90-day window")

    monkeypatch.setattr(
        update_external_data,
        "fetch_external_data_rows_with_diagnostics",
        fake_fetch_external_data_rows_with_diagnostics,
    )
    monkeypatch.setattr(update_external_data, "upsert_external_data_points", lambda rows: upserted_rows.extend(rows))

    update_external_data.main()

    assert call_log == [
        (window_7, ("dollar_index", "usd_cnh")),
        (window_30, ("dollar_index",)),
    ]
    assert [row["indicator_key"] for row in upserted_rows] == ["usd_cnh", "dollar_index"]
    output = capsys.readouterr().out
    assert f"external_data window=7d start={window_7} pending=2 resolved=1" in output
    assert f"external_data window=30d start={window_30} pending=1 resolved=1" in output
    assert f"external_data summary window=7d ok=1 proxy=0 no_data=1 fetch_failed=0 dns_failed=0" in output
    assert "external_data rows=2 indicators_ok=2/2" in output
    assert "usd_cnh: status=ok source=forex_hist_em:USDCNH error=-" in output
    assert "dollar_index: status=ok source=index_global_hist_em:.DXY error=-" in output


def test_script_stops_retrying_fetch_failed_indicators(monkeypatch, capsys) -> None:
    """Window expansion should stop for indicators that already failed at the connection layer."""
    today = dt.date.today()
    window_7 = (today - dt.timedelta(days=7)).strftime("%Y%m%d")
    window_30 = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    window_90 = (today - dt.timedelta(days=90)).strftime("%Y%m%d")
    call_log: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(update_external_data, "init_db", lambda: None)
    monkeypatch.setattr(
        update_external_data,
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
                        "eur_cnh": {"status": "fetch_failed", "source": None, "error": "RemoteDisconnected"},
                        "gold_td": {"status": "no_data", "source": None, "error": None},
                    }
                },
            )
        if start_date == window_30:
            return (
                [],
                {
                    "indicator_status": {
                        "gold_td": {"status": "no_data", "source": None, "error": None},
                    }
                },
            )
        if start_date == window_90:
            return (
                [],
                {
                    "indicator_status": {
                        "gold_td": {"status": "no_data", "source": None, "error": None},
                    }
                },
            )
        raise AssertionError(f"unexpected window={start_date}")

    monkeypatch.setattr(
        update_external_data,
        "fetch_external_data_rows_with_diagnostics",
        fake_fetch_external_data_rows_with_diagnostics,
    )
    monkeypatch.setattr(update_external_data, "upsert_external_data_points", lambda rows: None)

    update_external_data.main()

    assert call_log == [
        (window_7, ("eur_cnh", "gold_td")),
        (window_30, ("gold_td",)),
        (window_90, ("gold_td",)),
    ]
    output = capsys.readouterr().out
    assert f"external_data summary window=7d ok=0 proxy=0 no_data=1 fetch_failed=1 dns_failed=0" in output
    assert "eur_cnh: status=fetch_failed source=- error=RemoteDisconnected" in output
