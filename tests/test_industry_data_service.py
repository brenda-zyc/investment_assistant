from __future__ import annotations

import datetime as dt
import threading
import pandas as pd
import requests

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


def test_industry_indicator_specs_use_index_keys_and_display_names() -> None:
    specs = industry.get_industry_indicator_specs()
    keys = {item["indicator_key"] for item in specs}

    assert "thermal_coal_index" in keys
    assert "cement_price_index" in keys
    assert "thermal_coal" not in keys
    assert "cement_price" not in keys

    thermal = next(item for item in specs if item["indicator_key"] == "thermal_coal_index")
    cement = next(item for item in specs if item["indicator_key"] == "cement_price_index")

    assert thermal["display_name"] == "动力煤价格指数（CCI5500）"
    assert cement["display_name"] == "水泥价格指数（CEMPI）"


def test_expected_hosts_for_spec_supports_new_index_sources() -> None:
    thermal = {
        "indicator_key": "thermal_coal_index",
        "special_source": "sxcoal_cci5500",
    }
    cement = {
        "indicator_key": "cement_price_index",
        "special_source": "cempi_index",
    }

    thermal_hosts = industry._expected_hosts_for_spec(thermal)
    cement_hosts = industry._expected_hosts_for_spec(cement)

    assert "www.sxcoal.com" in thermal_hosts
    assert "index.ccement.com" in cement_hosts


def test_fetch_single_industry_series_routes_new_index_sources(monkeypatch) -> None:
    thermal_spec = {
        "indicator_key": "thermal_coal_index",
        "special_source": "sxcoal_cci5500",
    }
    cement_spec = {
        "indicator_key": "cement_price_index",
        "special_source": "cempi_index",
    }

    monkeypatch.setattr(
        industry,
        "_fetch_sxcoal_cci5500_series",
        lambda start_date=None, end_date=None: [("2026-04-09", 762.0)],
    )
    monkeypatch.setattr(
        industry,
        "_fetch_cempi_index_series",
        lambda start_date=None, end_date=None: [("2026-04-08", 101.2)],
    )

    thermal_points, thermal_source = industry._fetch_single_industry_series(
        thermal_spec,
        start_date="20260401",
        end_date="20260410",
    )
    cement_points, cement_source = industry._fetch_single_industry_series(
        cement_spec,
        start_date="20260401",
        end_date="20260410",
    )

    assert thermal_points == [("2026-04-09", 762.0)]
    assert thermal_source == "sxcoal_cci5500"
    assert cement_points == [("2026-04-08", 101.2)]
    assert cement_source == "cempi_index"


def test_parse_cempi_index_html_rejects_placeholder_like_value() -> None:
    """CEMPI parser should reject placeholder-like matches such as rank/order values."""
    html = """
    <html>
      <body>
        <div>2026-04-10 全国水泥价格指数 CEMPI 排名 1</div>
      </body>
    </html>
    """

    assert industry._parse_cempi_index_html(html) == []


def test_parse_cempi_index_html_accepts_reasonable_index_value() -> None:
    """CEMPI parser should keep realistic index values from the public page."""
    html = """
    <html>
      <body>
        <div>2026-04-10 全国水泥价格指数 CEMPI 101.2</div>
      </body>
    </html>
    """

    assert industry._parse_cempi_index_html(html) == [("2026-04-10", 101.2)]


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


def test_fetch_industry_price_rows_with_diagnostics_marks_sxcoal_403_as_blocked(monkeypatch) -> None:
    """Thermal-coal index should distinguish source blocking from generic fetch failures."""
    specs = [
        {
            "industry": "Energy",
            "indicator_key": "thermal_coal_index",
            "indicator": "thermal_coal_index",
            "special_source": "sxcoal_cci5500",
        }
    ]

    monkeypatch.setattr(industry, "INDUSTRY_INDICATOR_SPECS", specs)
    monkeypatch.setattr(industry, "_build_dns_snapshot", lambda: {"www.sxcoal.com": "dns_ok"})
    monkeypatch.setattr(industry, "_expected_hosts_for_spec", lambda _spec: ["www.sxcoal.com"])
    monkeypatch.setattr(industry, "_resolve_source_hosts", lambda _source_name: ["www.sxcoal.com"])

    http_error = requests.HTTPError("403 Client Error: Forbidden for url: https://www.sxcoal.com/")
    response = requests.Response()
    response.status_code = 403
    http_error.response = response

    def fail_fetch_single(*_args, **_kwargs):
        raise http_error

    monkeypatch.setattr(industry, "_fetch_single_industry_series", fail_fetch_single)

    rows, diagnostics = industry.fetch_industry_price_rows_with_diagnostics(
        start_date="20260401",
        end_date="20260410",
    )

    assert rows == []
    status_map = diagnostics["indicator_status"]
    assert status_map["thermal_coal_index"]["status"] == "blocked"
    assert "403" in (status_map["thermal_coal_index"]["error"] or "")


def test_fetch_industry_price_rows_with_diagnostics_fetches_indicators_concurrently(monkeypatch) -> None:
    specs = [
        {"industry": "A", "indicator_key": "left_indicator", "indicator": "left_indicator"},
        {"industry": "B", "indicator_key": "right_indicator", "indicator": "right_indicator"},
    ]
    barrier = threading.Barrier(2, timeout=0.2)

    monkeypatch.setattr(industry, "INDUSTRY_INDICATOR_SPECS", specs)
    monkeypatch.setattr(industry, "_build_dns_snapshot", lambda: {"ok.host": "dns_ok"})
    monkeypatch.setattr(industry, "_expected_hosts_for_spec", lambda _spec: ["ok.host"])
    monkeypatch.setattr(industry, "_resolve_source_hosts", lambda _source_name: ["ok.host"])

    def fake_fetch_single(spec: dict[str, str], start_date: str, end_date: str):  # noqa: ANN001
        assert start_date == "20240101"
        assert end_date == "20240131"
        barrier.wait()
        return [("2024-01-05", 1.0)], f"futures_zh_daily_sina:{spec['indicator_key']}"

    monkeypatch.setattr(industry, "_fetch_single_industry_series", fake_fetch_single)

    rows, diagnostics = industry.fetch_industry_price_rows_with_diagnostics(
        start_date="20240101",
        end_date="20240131",
    )

    assert [row["indicator"] for row in rows] == ["left_indicator", "right_indicator"]
    assert diagnostics["indicator_status"]["left_indicator"]["status"] == "ok"
    assert diagnostics["indicator_status"]["right_indicator"]["status"] == "ok"


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


def test_fetch_external_data_rows_uses_fetch_source_metadata(monkeypatch) -> None:
    """Displayed external source metadata should follow the actual fetch source when a fallback path is used."""
    specs = [
        {
            "indicator_key": "gold_td",
            "indicator": "黄金T+D",
            "fetch_kind": "sge_spot",
            "symbol": "Au(T+D)",
            "source": "上海黄金交易所",
            "source_url": "https://www.sge.com.cn/sjzx/mrhq",
            "note": "直接抓取上金所 Au(T+D) 历史行情最新值。",
            "status_on_success": "ok",
        },
        {
            "indicator_key": "thermal_coal_5500k",
            "indicator": "煤炭5500K：动力煤",
            "fetch_kind": "thermal_coal_proxy",
            "sina_contract": "ZC0",
            "basis_var": "ZC",
            "source": "新浪财经",
            "source_url": "https://finance.sina.com.cn/futures/quotes/ZC0.shtml",
            "note": "优先抓取新浪动力煤主连日线，失败时回退到 100ppi 代理值。",
            "status_on_success": "ok",
        },
    ]

    monkeypatch.setattr(industry, "EXTERNAL_DATA_SPECS", specs)
    monkeypatch.setattr(industry, "_build_dns_snapshot", lambda: {})
    monkeypatch.setattr(industry, "_expected_hosts_for_external_spec", lambda spec: [])

    def fake_fetch_single(spec: dict[str, str], start_date: str, end_date: str):  # noqa: ANN001
        if spec["indicator_key"] == "gold_td":
            return [("2026-04-02", 588.2)], "spot_hist_sge:Au(T+D)"
        return [("2026-04-01", 747.0)], "futures_spot_price_daily:ZC"

    monkeypatch.setattr(industry, "_fetch_single_external_series", fake_fetch_single)

    rows, diagnostics = industry.fetch_external_data_rows_with_diagnostics(
        start_date="20260401",
        end_date="20260408",
    )

    gold_td_row = next(row for row in rows if row["indicator_key"] == "gold_td")
    thermal_coal_row = next(row for row in rows if row["indicator_key"] == "thermal_coal_5500k")

    assert gold_td_row["source"] == "上海黄金交易所"
    assert gold_td_row["source_url"] == "https://www.sge.com.cn/sjzx/mrhq"
    assert thermal_coal_row["source"] == "100ppi（代理）"
    assert thermal_coal_row["source_url"] == "https://www.100ppi.com/sf/"
    assert diagnostics["indicator_status"]["thermal_coal_5500k"]["status"] == "proxy"


def test_fetch_external_data_rows_with_diagnostics_skips_fetch_when_dns_preflight_fails(monkeypatch) -> None:
    """External indicators should fast-fail before network fetch when every expected host is unresolvable."""
    specs = [
        {
            "indicator_key": "usd_cnh",
            "indicator": "USD/CNH",
            "source": "Source A",
            "source_url": "https://example.com/a",
            "note": "note-a",
            "status_on_success": "ok",
        }
    ]

    monkeypatch.setattr(industry, "EXTERNAL_DATA_SPECS", specs)
    monkeypatch.setattr(industry, "_build_dns_snapshot", lambda: {"bad.host": "dns_failed"})
    monkeypatch.setattr(industry, "_expected_hosts_for_external_spec", lambda spec: ["bad.host"])

    def fail_fetch_single(*_args, **_kwargs):
        raise AssertionError("fetch should be skipped when DNS preflight already failed")

    monkeypatch.setattr(industry, "_fetch_single_external_series", fail_fetch_single)

    rows, diagnostics = industry.fetch_external_data_rows_with_diagnostics(
        start_date="20240101",
        end_date="20240131",
    )

    assert rows == []
    status_map = diagnostics["indicator_status"]
    assert status_map["usd_cnh"]["status"] == "dns_failed"
    assert status_map["usd_cnh"]["source"] is None


def test_fetch_industry_price_rows_with_diagnostics_skips_fetch_when_dns_preflight_fails(monkeypatch) -> None:
    """Industry indicators should fast-fail before network fetch when every expected host is unresolvable."""
    specs = [
        {"industry": "Agriculture", "indicator_key": "pork_price", "indicator": "pork_price"},
    ]

    monkeypatch.setattr(industry, "INDUSTRY_INDICATOR_SPECS", specs)
    monkeypatch.setattr(industry, "_build_dns_snapshot", lambda: {"bad.host": "dns_failed"})
    monkeypatch.setattr(industry, "_expected_hosts_for_spec", lambda spec: ["bad.host"])

    def fail_fetch_single(*_args, **_kwargs):
        raise AssertionError("fetch should be skipped when DNS preflight already failed")

    monkeypatch.setattr(industry, "_fetch_single_industry_series", fail_fetch_single)

    rows, diagnostics = industry.fetch_industry_price_rows_with_diagnostics(
        start_date="20240101",
        end_date="20240131",
    )

    assert rows == []
    status_map = diagnostics["indicator_status"]
    assert status_map["pork_price"]["status"] == "dns_failed"
    assert status_map["pork_price"]["source"] is None


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


def test_fetch_moa_beef_series_parses_latest_article_listing(monkeypatch) -> None:
    """Beef-price fetcher should parse official MOA market-info article links into dated points."""

    class DummyResponse:
        """Minimal HTTP response stub for MOA listing/article pages."""

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    listing_html = """
    <html>
      <body>
        <ul>
          <li><a href="/scxxfb/202504/t20250402_6472718.htm">4月2日：牛肉价格比昨天上升0.9%</a></li>
          <li><a href="/scxxfb/202504/t20250402_6472719.htm">4月2日：鸡蛋价格比昨天持平</a></li>
        </ul>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <h1>4月2日：牛肉价格比昨天上升0.9%</h1>
        <div class="time">2025年04月02日 16:00</div>
        <div id="zoom">
          全国牛肉平均批发价格每公斤60.20元，比昨天上升0.9%。
        </div>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int = 10):  # noqa: ARG001
        if url == "https://scs.moa.gov.cn/scxxfb/":
            return DummyResponse(listing_html)
        if url == "https://scs.moa.gov.cn/scxxfb/index_1.htm":
            return DummyResponse("<html><body></body></html>")
        if url == "https://scs.moa.gov.cn/scxxfb/202504/t20250402_6472718.htm":
            return DummyResponse(article_html)
        raise AssertionError(f"unexpected url={url}")

    monkeypatch.setattr(industry.requests, "get", fake_get)
    monkeypatch.setattr(industry, "_call_with_resilience", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    assert industry._fetch_moa_beef_series(max_pages=2) == [("2025-04-02", 60.2)]


def test_fetch_moa_beef_series_allows_generic_listing_titles(monkeypatch) -> None:
    """MOA beef parser should scan article bodies even when listing titles omit the 牛肉 keyword."""

    class DummyResponse:
        """Minimal HTTP response stub for MOA fallback listing pages."""

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    listing_html = """
    <html>
      <body>
        <ul>
          <li><a href="/xw/zxfb/202504/t20250408_6472890.htm">2025年第14周国内外农产品市场动态</a></li>
        </ul>
      </body>
    </html>
    """
    article_html = """
    <html>
      <body>
        <h1>2025年第14周国内外农产品市场动态</h1>
        <div class="time">2025年04月08日</div>
        <div id="zoom">
          牛肉批发价格为每公斤61.80元，环比上涨1.2%。
        </div>
      </body>
    </html>
    """

    def fake_get(url: str, timeout: int = 10):  # noqa: ARG001
        if url == "https://scs.moa.gov.cn/scxxfb/":
            return DummyResponse("<html><body></body></html>")
        if url == "https://www.moa.gov.cn/xw/zxfb/":
            return DummyResponse(listing_html)
        if url == "https://www.moa.gov.cn/xw/zxfb/index_1.htm":
            return DummyResponse("<html><body></body></html>")
        if url == "https://www.moa.gov.cn/xw/zxfb/202504/t20250408_6472890.htm":
            return DummyResponse(article_html)
        raise AssertionError(f"unexpected url={url}")

    monkeypatch.setattr(industry.requests, "get", fake_get)
    monkeypatch.setattr(industry, "_call_with_resilience", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    assert industry._fetch_moa_beef_series(max_pages=2) == [("2025-04-08", 61.8)]


def test_fetch_moa_beef_series_prefers_newest_candidate_articles(monkeypatch) -> None:
    """MOA beef parser should keep the newest candidate articles when the candidate list is truncated."""

    class DummyResponse:
        """Minimal HTTP response stub for MOA article ordering test."""

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    recent_links = "\n".join(
        f'<li><a href="./20260{month}/t20260{month}01_647{month:04d}.htm">{month}月1日：“农产品批发价格200指数”快报</a></li>'
        for month in range(1, 10)
    )
    listing_html = f"<html><body><ul>{recent_links}</ul></body></html>"

    def fake_article(date_text: str, value: float) -> str:
        return f"""
        <html>
          <body>
            <div class=\"time\">{date_text}</div>
            <div id=\"zoom\">牛肉{value:.2f}元/公斤。</div>
          </body>
        </html>
        """

    article_map = {
        f"https://www.moa.gov.cn/xw/zxfb/20260{month}/t20260{month}01_647{month:04d}.htm": fake_article(
            f"2026年0{month}月01日",
            60 + month,
        )
        for month in range(1, 10)
    }

    def fake_get(url: str, timeout: int = 10):  # noqa: ARG001
        if url == "https://scs.moa.gov.cn/scxxfb/":
            return DummyResponse("<html><body></body></html>")
        if url == "https://www.moa.gov.cn/xw/zxfb/":
            return DummyResponse(listing_html)
        if url in article_map:
            return DummyResponse(article_map[url])
        raise AssertionError(f"unexpected url={url}")

    monkeypatch.setattr(industry.requests, "get", fake_get)
    monkeypatch.setattr(industry, "_call_with_resilience", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    points = industry._fetch_moa_beef_series(max_pages=1)

    assert points[-1] == ("2026-09-01", 69.0)


def test_fetch_moa_beef_series_stops_after_crossing_requested_start_date(monkeypatch) -> None:
    """Incremental refresh should stop reading older beef articles once it has crossed the requested start date."""

    class DummyResponse:
        """Minimal HTTP response stub for MOA incremental backfill test."""

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            """Mirror requests response API without error."""

    listing_html = """
    <html>
      <body>
        <ul>
          <li><a href="./202604/t20260407_6483020.htm">4月7日：“农产品批发价格200指数”快报</a></li>
          <li><a href="./202604/t20260403_6482948.htm">4月3日：“农产品批发价格200指数”快报</a></li>
          <li><a href="./202603/t20260310_6482000.htm">3月10日：“农产品批发价格200指数”快报</a></li>
          <li><a href="./202603/t20260301_6481000.htm">3月1日：“农产品批发价格200指数”快报</a></li>
        </ul>
      </body>
    </html>
    """
    article_hits: list[str] = []
    article_map = {
        "https://www.moa.gov.cn/xw/zxfb/202604/t20260407_6483020.htm": """
        <html><body><div class=\"time\">2026年04月07日</div><div id=\"zoom\">牛肉66.52元/公斤。</div></body></html>
        """,
        "https://www.moa.gov.cn/xw/zxfb/202604/t20260403_6482948.htm": """
        <html><body><div class=\"time\">2026年04月03日</div><div id=\"zoom\">牛肉66.40元/公斤。</div></body></html>
        """,
        "https://www.moa.gov.cn/xw/zxfb/202603/t20260310_6482000.htm": """
        <html><body><div class=\"time\">2026年03月10日</div><div id=\"zoom\">牛肉65.90元/公斤。</div></body></html>
        """,
        "https://www.moa.gov.cn/xw/zxfb/202603/t20260301_6481000.htm": """
        <html><body><div class=\"time\">2026年03月01日</div><div id=\"zoom\">牛肉65.10元/公斤。</div></body></html>
        """,
    }

    def fake_get(url: str, timeout: int = 10):  # noqa: ARG001
        if url == "https://scs.moa.gov.cn/scxxfb/":
            return DummyResponse("<html><body></body></html>")
        if url == "https://www.moa.gov.cn/xw/zxfb/":
            return DummyResponse(listing_html)
        if url in article_map:
            article_hits.append(url)
            return DummyResponse(article_map[url])
        raise AssertionError(f"unexpected url={url}")

    monkeypatch.setattr(industry.requests, "get", fake_get)
    monkeypatch.setattr(industry, "_call_with_resilience", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    points = industry._fetch_moa_beef_series(start_date="20260309", max_pages=1)

    assert points == [
        ("2026-03-10", 65.9),
        ("2026-04-03", 66.4),
        ("2026-04-07", 66.52),
    ]
    assert "https://www.moa.gov.cn/xw/zxfb/202603/t20260301_6481000.htm" not in article_hits


def test_fetch_single_industry_series_uses_incremental_beef_window(monkeypatch) -> None:
    """Request-path beef refresh should pass the bounded incremental window into the MOA fetcher."""
    captured: dict[str, object] = {}
    spec = {"indicator_key": "beef_price", "special_source": "moa_beef"}

    def fake_fetch_moa_beef_series(**kwargs):
        captured.update(kwargs)
        return [("2026-04-07", 66.52)]

    monkeypatch.setattr(industry, "_fetch_moa_beef_series", fake_fetch_moa_beef_series)

    points, source = industry._fetch_single_industry_series(spec, "20260309", "20260408")

    assert points == [("2026-04-07", 66.52)]
    assert source == "moa_market_info"
    assert captured["start_date"] == "20260309"
    assert captured["end_date"] == "20260408"
    assert captured["max_pages"] == 1
    assert captured["max_articles"] == 12


def test_fetch_single_industry_series_falls_back_to_sina_when_global_hist_fails(monkeypatch) -> None:
    """Industry refresh should continue to Sina fallback when the global futures source errors out."""
    spec = {
        "indicator_key": "brent_oil",
        "global_symbols": "B00Y,CL00Y",
        "sina_contract": "SC0",
    }

    monkeypatch.setattr(
        industry,
        "_fetch_futures_global_hist_series",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("RemoteDisconnected")),
    )
    monkeypatch.setattr(
        industry,
        "_fetch_futures_daily_sina_series",
        lambda contract_symbol, start_date, end_date: [("2026-04-07", 710.0)] if contract_symbol == "SC0" else [],
    )

    points, source = industry._fetch_single_industry_series(spec, "20260309", "20260408")

    assert points == [("2026-04-07", 710.0)]
    assert source == "futures_zh_daily_sina:SC0"


def test_fetch_single_external_series_uses_sge_for_gold_td(monkeypatch) -> None:
    """Gold T+D should use the SGE history source instead of Eastmoney global futures."""
    spec = {"fetch_kind": "sge_spot", "symbol": "Au(T+D)"}

    monkeypatch.setattr(
        industry,
        "_fetch_sge_spot_hist_series",
        lambda symbol, start_date, end_date: [("2026-04-02", 588.2)] if symbol == "Au(T+D)" else [],
    )

    points, source = industry._fetch_single_external_series(spec, "20260301", "20260408")

    assert points == [("2026-04-02", 588.2)]
    assert source == "spot_hist_sge:Au(T+D)"


def test_fetch_sxcoal_cci5500_series_parses_latest_point(monkeypatch) -> None:
    html = """
    <html><body>
      <a href="/news/detail/2042173180508495873">4月9日CCI5500动力煤价格指数上涨2.0元</a>
      <div>CCI5500 762 元/吨</div>
    </body></html>
    """

    class FakeResponse:
        text = html

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(industry.requests, "get", lambda *args, **kwargs: FakeResponse())

    assert industry._fetch_sxcoal_cci5500_series() == [("2026-04-09", 762.0)]


def test_fetch_cempi_index_series_parses_latest_point(monkeypatch) -> None:
    html = """
    <html><body>
      <div>CEMPI</div>
      <div>2026-04-08</div>
      <div>101.23</div>
    </body></html>
    """

    class FakeResponse:
        text = html

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(industry.requests, "get", lambda *args, **kwargs: FakeResponse())

    assert industry._fetch_cempi_index_series() == [("2026-04-08", 101.23)]


def test_fetch_single_external_series_uses_sina_before_basis_proxy(monkeypatch) -> None:
    """Thermal coal should prefer Sina daily data and only fall back to basis proxy when needed."""
    spec = {"fetch_kind": "thermal_coal_proxy", "sina_contract": "ZC0", "basis_var": "ZC"}

    monkeypatch.setattr(
        industry,
        "_fetch_futures_daily_sina_series",
        lambda contract, start_date, end_date: [("2026-04-02", 742.0)] if contract == "ZC0" else [],
    )
    monkeypatch.setattr(
        industry,
        "_fetch_futures_basis_series",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("basis fallback should not run")),
    )

    points, source = industry._fetch_single_external_series(spec, "20260301", "20260408")

    assert points == [("2026-04-02", 742.0)]
    assert source == "futures_zh_daily_sina:ZC0"


def test_fetch_single_external_series_falls_back_to_basis_proxy_for_thermal_coal(monkeypatch) -> None:
    """Thermal coal should still use the 100ppi proxy when Sina returns no rows."""
    spec = {"fetch_kind": "thermal_coal_proxy", "sina_contract": "ZC0", "basis_var": "ZC"}

    monkeypatch.setattr(industry, "_fetch_futures_daily_sina_series", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        industry,
        "_fetch_futures_basis_series",
        lambda basis_var, start_date, end_date: [("2026-04-01", 747.0)] if basis_var == "ZC" else [],
    )

    points, source = industry._fetch_single_external_series(spec, "20260301", "20260408")

    assert points == [("2026-04-01", 747.0)]
    assert source == "futures_spot_price_daily:ZC"


def test_fetch_futures_global_hist_series_raises_after_all_candidates_fail(monkeypatch) -> None:
    """Connection-level global futures failures should surface as fetch_failed instead of silent no_data."""

    def fail_resilience(*_args, **_kwargs):
        raise RuntimeError("RemoteDisconnected")

    monkeypatch.setattr(industry, "_call_with_resilience", fail_resilience)

    try:
        industry._fetch_futures_global_hist_series(["SI00Y", "GC00Y"], "20260401", "20260408")
    except RuntimeError as exc:
        assert "RemoteDisconnected" in str(exc)
    else:  # pragma: no cover - explicit failure branch for readability
        raise AssertionError("expected global history fetch to propagate the last upstream exception")


def test_external_data_is_stale_uses_weekly_window() -> None:
    fresh_date = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    stale_date = (dt.date.today() - dt.timedelta(days=12)).isoformat()

    from app.usecases import industry_usecase

    assert industry_usecase.external_data_is_stale([{"trade_date": fresh_date}]) is False
    assert industry_usecase.external_data_is_stale([{"trade_date": stale_date}]) is True
