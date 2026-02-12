from __future__ import annotations

import pandas as pd

from app.services import industry_data_service as industry


def test_normalize_history_frame_filters_invalid_and_dedupes() -> None:
    df = pd.DataFrame(
        [
            {"日期": "2024-01-03", "最新值": "10"},
            {"日期": "bad-date", "最新值": "20"},
            {"日期": "2024-01-02", "最新值": None},
            {"日期": "2024-01-01", "最新值": "5"},
            {"日期": "2024-01-03", "最新值": "12"},  # duplicate date; latest row should win
        ]
    )

    points = industry._normalize_history_frame(df, "日期", "最新值")
    assert points == [("2024-01-01", 5.0), ("2024-01-03", 12.0)]


def test_fetch_industry_price_rows_with_diagnostics_deterministic(monkeypatch) -> None:
    specs = [
        {"industry": "A", "indicator_key": "ok_indicator", "indicator": "ok_indicator"},
        {"industry": "B", "indicator_key": "dns_indicator", "indicator": "dns_indicator"},
        {"industry": "C", "indicator_key": "err_indicator", "indicator": "err_indicator"},
    ]

    monkeypatch.setattr(industry, "INDUSTRY_INDICATOR_SPECS", specs)
    monkeypatch.setattr(
        industry,
        "_build_dns_snapshot",
        lambda: {
            "ok.host": "dns_ok",
            "bad.host": "dns_failed",
        },
    )
    monkeypatch.setattr(
        industry,
        "_expected_hosts_for_spec",
        lambda spec: ["bad.host"] if spec["indicator_key"] == "dns_indicator" else ["ok.host"],
    )
    monkeypatch.setattr(
        industry,
        "_resolve_source_hosts",
        lambda source_name: ["ok.host"] if source_name == "futures_zh_daily_sina" else [],
    )

    def fake_fetch_single(spec: dict[str, str], start_date: str, end_date: str):  # noqa: ANN001
        assert start_date == "20240101"
        assert end_date == "20240131"
        if spec["indicator_key"] == "ok_indicator":
            return [("2024-01-05", 11.5)], "futures_zh_daily_sina:RB0"
        if spec["indicator_key"] == "dns_indicator":
            return [], ""
        raise RuntimeError("upstream error")

    monkeypatch.setattr(industry, "_fetch_single_industry_series", fake_fetch_single)

    rows, diagnostics = industry.fetch_industry_price_rows_with_diagnostics(
        start_date="20240101",
        end_date="20240131",
    )

    assert rows == [
        {
            "industry": "A",
            "indicator": "ok_indicator",
            "trade_date": "2024-01-05",
            "value": 11.5,
            "source": "futures_zh_daily_sina:RB0",
        }
    ]

    status_map = diagnostics["indicator_status"]
    assert status_map["ok_indicator"]["status"] == "ok"
    assert status_map["ok_indicator"]["source"] == "futures_zh_daily_sina:RB0"
    assert status_map["dns_indicator"]["status"] == "dns_failed"
    assert status_map["err_indicator"]["status"] == "fetch_failed"
    assert "upstream error" in (status_map["err_indicator"]["error"] or "")


def test_fetch_industry_price_rows_returns_rows_only(monkeypatch) -> None:
    expected_rows = [{"indicator": "x"}]
    monkeypatch.setattr(
        industry,
        "fetch_industry_price_rows_with_diagnostics",
        lambda start_date=None, end_date=None: (expected_rows, {"noop": True}),
    )

    assert industry.fetch_industry_price_rows() == expected_rows
