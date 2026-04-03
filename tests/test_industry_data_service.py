from __future__ import annotations

import datetime as dt
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


def test_fetch_external_data_rows_with_diagnostics_deterministic(monkeypatch) -> None:
    specs = [
        {
            "indicator_key": "ok_indicator",
            "indicator": "OK",
            "source": "Source A",
            "source_url": "https://example.com/a",
            "note": "note-a",
            "status_on_success": "ok",
        },
        {
            "indicator_key": "proxy_indicator",
            "indicator": "Proxy",
            "source": "Source B",
            "source_url": "https://example.com/b",
            "note": "note-b",
            "status_on_success": "proxy",
        },
        {
            "indicator_key": "dns_indicator",
            "indicator": "DNS",
            "source": "Source C",
            "source_url": "https://example.com/c",
            "note": "note-c",
            "status_on_success": "ok",
        },
    ]

    monkeypatch.setattr(industry, "EXTERNAL_DATA_SPECS", specs)
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
        "_expected_hosts_for_external_spec",
        lambda spec: ["bad.host"] if spec["indicator_key"] == "dns_indicator" else ["ok.host"],
    )

    def fake_fetch_single(spec: dict[str, str], start_date: str, end_date: str):  # noqa: ANN001
        assert start_date == "20240101"
        assert end_date == "20240131"
        if spec["indicator_key"] == "ok_indicator":
            return [("2024-01-05", 11.5)], "fetcher:ok"
        if spec["indicator_key"] == "proxy_indicator":
            return [("2024-01-06", 22.0)], "fetcher:proxy"
        return [], ""

    monkeypatch.setattr(industry, "_fetch_single_external_series", fake_fetch_single)

    rows, diagnostics = industry.fetch_external_data_rows_with_diagnostics(
        start_date="20240101",
        end_date="20240131",
    )

    assert rows == [
        {
            "indicator_key": "ok_indicator",
            "indicator": "OK",
            "trade_date": "2024-01-05",
            "value": 11.5,
            "source": "Source A",
            "source_url": "https://example.com/a",
            "note": "note-a",
        },
        {
            "indicator_key": "proxy_indicator",
            "indicator": "Proxy",
            "trade_date": "2024-01-06",
            "value": 22.0,
            "source": "Source B",
            "source_url": "https://example.com/b",
            "note": "note-b",
        },
    ]

    status_map = diagnostics["indicator_status"]
    assert status_map["ok_indicator"]["status"] == "ok"
    assert status_map["ok_indicator"]["source"] == "fetcher:ok"
    assert status_map["proxy_indicator"]["status"] == "proxy"
    assert status_map["dns_indicator"]["status"] == "dns_failed"


def test_fetch_us_treasury_curve_series_falls_back_to_unverified_html(monkeypatch) -> None:
    """Treasury parser should fall back to verify=False when local cert trust is incomplete."""
    industry._TREASURY_CURVE_TABLE_CACHE.clear()

    class DummyResponse:
        """Minimal requests response stub for HTML table fallback."""

        text = """
        <table>
          <thead>
            <tr><th>Date</th><th>6 Mo</th><th>10 Yr</th></tr>
          </thead>
          <tbody>
            <tr><td>2026-04-01</td><td>4.12</td><td>4.35</td></tr>
            <tr><td>2026-04-02</td><td>4.10</td><td>4.30</td></tr>
          </tbody>
        </table>
        """

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    calls = {"count": 0}

    def fake_resilience(func, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("ssl verify failed")
        return func(*args, **kwargs)

    monkeypatch.setattr(industry, "_call_with_resilience", fake_resilience)
    monkeypatch.setattr(industry.requests, "get", lambda *args, **kwargs: DummyResponse())

    points = industry._fetch_us_treasury_curve_series("6 Mo")

    assert points == [("2026-04-01", 4.12), ("2026-04-02", 4.1)]


def test_fetch_us_treasury_curve_series_reuses_cached_tables(monkeypatch) -> None:
    """Treasury 6M and 10Y should share one fetched table snapshot per month."""
    industry._TREASURY_CURVE_TABLE_CACHE.clear()
    calls = {"count": 0}

    class DummyResponse:
        """Minimal requests response stub for treasury HTML cache test."""

        text = """
        <table>
          <thead>
            <tr><th>Date</th><th>6 Mo</th><th>10 Yr</th></tr>
          </thead>
          <tbody>
            <tr><td>2026-04-01</td><td>4.12</td><td>4.35</td></tr>
          </tbody>
        </table>
        """

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    def fake_get(*_args, **_kwargs):
        calls["count"] += 1
        return DummyResponse()

    resilience_calls = {"count": 0}

    def fake_resilience(func, *args, **kwargs):  # noqa: ANN001
        resilience_calls["count"] += 1
        if resilience_calls["count"] == 1:
            raise RuntimeError("ssl verify failed")
        return func(*args, **kwargs)

    monkeypatch.setattr(industry, "_call_with_resilience", fake_resilience)
    monkeypatch.setattr(industry.requests, "get", fake_get)

    assert industry._fetch_us_treasury_curve_series("6 Mo") == [("2026-04-01", 4.12)]
    assert industry._fetch_us_treasury_curve_series("10 Yr") == [("2026-04-01", 4.35)]
    assert calls["count"] == 1


def test_fetch_zhaomei_water_coal_series_parses_homepage_html(monkeypatch) -> None:
    """Water-coal parser should read the public homepage date and price block."""
    html = """
    <div class="title-font">环渤海<span style="color: #308AEC;">水泥煤</span>现货参考价</div>
    <div class="floor_subtitle">2026-04-01</div>
    <div id="priceContent" class="floor-content">
      <div class="floor-box">
        <ul>
          <li class="down">
            <div class="hd"><span>水泥煤5500K 1.0S</span></div>
            <div class="bd"><span>762</span>元/吨</div>
          </li>
        </ul>
      </div>
    </div>
    """

    monkeypatch.setattr(industry, "_call_with_resilience", lambda fn: html)

    assert industry._fetch_zhaomei_water_coal_series() == [("2026-04-01", 762.0)]


def test_external_data_is_stale_uses_weekly_window() -> None:
    fresh_date = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    stale_date = (dt.date.today() - dt.timedelta(days=12)).isoformat()

    from app.usecases import industry_usecase

    assert industry_usecase.external_data_is_stale([{"trade_date": fresh_date}]) is False
    assert industry_usecase.external_data_is_stale([{"trade_date": stale_date}]) is True
