from __future__ import annotations

from app.core_logic import (
    compute_financial_report_analysis,
    compute_latest_close_percentile,
    compute_macro_signals,
    compute_percentile_from_points,
    compute_stock_metrics,
    signal_from_percentile,
    to_float,
)


def test_to_float_handles_valid_and_invalid_values() -> None:
    assert to_float(1) == 1.0
    assert to_float("2.5") == 2.5
    assert to_float(None) is None
    assert to_float("bad") is None


def test_compute_latest_close_percentile_empty_and_insufficient() -> None:
    assert compute_latest_close_percentile([]) is None
    assert compute_latest_close_percentile([{"close": None}, {"close": "-"}]) is None
    assert compute_latest_close_percentile([{"close": 10.0}]) is None


def test_compute_latest_close_percentile_normal_case() -> None:
    rows = [
        {"close": 10.0},  # latest
        {"close": 20.0},
        {"close": 5.0},
        {"close": 10.0},
        {"close": None},
    ]
    # <= 10.0: [10, 5, 10] => 3 / 4 = 75%
    assert compute_latest_close_percentile(rows) == 75


def test_compute_percentile_from_points_empty_and_insufficient() -> None:
    empty = compute_percentile_from_points([])
    assert empty == {
        "value": None,
        "percentile": None,
        "as_of": None,
        "data_insufficient": True,
        "sample_size": 0,
    }

    insufficient = compute_percentile_from_points(
        [("2024-01-01", 1.0), ("2024-01-02", 2.0)],
        min_samples=3,
    )
    assert insufficient["value"] == 2.0
    assert insufficient["percentile"] is None
    assert insufficient["as_of"] == "2024-01-02"
    assert insufficient["data_insufficient"] is True
    assert insufficient["sample_size"] == 2


def test_compute_percentile_from_points_with_cleaning_and_percentile() -> None:
    points = [(f"2024-01-{i:02d}", float(i)) for i in range(1, 25)] + [("2024-01-26", None)]
    result = compute_percentile_from_points(points, min_samples=24)
    assert result["value"] == 24.0
    assert result["percentile"] == 100
    assert result["as_of"] == "2024-01-24"
    assert result["data_insufficient"] is False
    assert result["sample_size"] == 24


def test_signal_from_percentile_thresholds() -> None:
    assert signal_from_percentile(0) == ("Undervalued", "green")
    assert signal_from_percentile(19) == ("Undervalued", "green")
    assert signal_from_percentile(20) == ("Neutral", "yellow")
    assert signal_from_percentile(60) == ("Neutral", "yellow")
    assert signal_from_percentile(61) == ("Expensive", "red")


def test_compute_macro_signals_empty_and_sorted_output() -> None:
    assert compute_macro_signals([]) == []

    rows = [
        {"date": "2024-01-03", "b_metric": 3.0, "china_pmi": 49.0, "skip": None},
        {"date": "2024-01-02", "b_metric": 2.0, "china_pmi": 50.5, "skip": None},
        {"date": "2024-01-01", "b_metric": 1.0, "china_pmi": 48.0, "skip": None},
    ]

    out = compute_macro_signals(rows)
    indicators = [item["indicator"] for item in out]
    assert indicators == sorted(indicators)

    b_metric = [item for item in out if item["indicator"] == "b_metric"][0]
    assert b_metric["value"] == 3.0
    assert b_metric["percentile"] == 100
    assert b_metric["signal_label"] == "Expensive"
    assert b_metric["signal_color"] == "red"

    pmi = [item for item in out if item["indicator"] == "china_pmi"][0]
    assert pmi["value"] == 49.0
    assert pmi["signal_label"] == "Contraction"
    assert pmi["signal_color"] == "red"

    # "skip" has no valid numeric history and should not be returned.
    assert not any(item["indicator"] == "skip" for item in out)


def test_compute_macro_signals_pmi_expansion_branch() -> None:
    rows = [
        {"date": "2024-01-02", "china_pmi": 50.0},
        {"date": "2024-01-01", "china_pmi": 49.9},
    ]
    out = compute_macro_signals(rows)
    assert out[0]["indicator"] == "china_pmi"
    assert out[0]["signal_label"] == "Expansion"
    assert out[0]["signal_color"] == "green"


def test_compute_stock_metrics_success_path() -> None:
    pe_series = [(f"2024-01-{i:02d}", float(i)) for i in range(1, 25)]
    pb_series = [(f"2024-02-{i:02d}", float(i)) for i in range(1, 25)]
    roe_series = [(f"2024-03-{i:02d}", float(i)) for i in range(1, 25)]
    roic_series = [(f"2024-04-{i:02d}", float(i)) for i in range(1, 25)]

    def valuation_fetcher(symbol: str) -> dict[str, list[tuple[str, float]]]:
        assert symbol == "000333"
        return {"pe_ttm": pe_series, "pb": pb_series}

    def financial_fetcher(symbol: str) -> dict[str, list[tuple[str, float]]]:
        assert symbol == "000333"
        return {"roe": roe_series, "roic": roic_series, "revenue": [("2024-01-01", 100.0)]}

    def cagr_builder(_revenue: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return [(f"2024-05-{i:02d}", float(i)) for i in range(1, 25)]

    payload = compute_stock_metrics(
        symbol="000333",
        fetch_valuation_series_fn=valuation_fetcher,
        fetch_financial_metric_series_fn=financial_fetcher,
        build_revenue_cagr_5y_series_fn=cagr_builder,
    )

    assert payload["symbol"] == "000333"
    assert payload["as_of"] == "2024-05-24"
    assert len(payload["metrics"]) == 5
    assert all(item["percentile"] == 100 for item in payload["metrics"])
    assert all(item["data_insufficient"] is False for item in payload["metrics"])


def test_compute_stock_metrics_with_fetch_failures_and_warning_hook() -> None:
    warnings: list[tuple[str, str, str]] = []

    def valuation_fetcher(_symbol: str) -> dict[str, list[tuple[str, float]]]:
        raise RuntimeError("valuation error")

    def financial_fetcher(_symbol: str) -> dict[str, list[tuple[str, float]]]:
        raise RuntimeError("financial error")

    def cagr_builder(_revenue: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return []

    def warn_hook(kind: str, symbol: str, exc: Exception) -> None:
        warnings.append((kind, symbol, str(exc)))

    payload = compute_stock_metrics(
        symbol="600519",
        fetch_valuation_series_fn=valuation_fetcher,
        fetch_financial_metric_series_fn=financial_fetcher,
        build_revenue_cagr_5y_series_fn=cagr_builder,
        warn_fn=warn_hook,
    )

    assert payload["symbol"] == "600519"
    assert payload["as_of"] is None
    assert len(payload["metrics"]) == 5
    assert all(item["value"] is None for item in payload["metrics"])
    assert all(item["percentile"] is None for item in payload["metrics"])
    assert all(item["data_insufficient"] is True for item in payload["metrics"])
    assert warnings == [
        ("valuation", "600519", "valuation error"),
        ("financial", "600519", "financial error"),
    ]


def test_compute_financial_report_analysis_empty_rows() -> None:
    payload = compute_financial_report_analysis([])
    assert payload["as_of"] is None
    assert payload["latest_report_year"] is None
    assert payload["score"] is None
    assert payload["grade"] is None
    assert payload["series"] == []
    assert payload["highlights"][0]["level"] == "info"


def test_compute_financial_report_analysis_normal_case() -> None:
    rows = [
        {
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": 150.0,
            "net_profit": 18.0,
            "roe": 16.0,
            "debt_ratio": 45.0,
        },
        {
            "report_year": 2023,
            "report_date": "2023-12-31",
            "revenue": 120.0,
            "net_profit": 12.0,
            "roe": 13.0,
            "debt_ratio": 50.0,
        },
        {
            "report_year": 2022,
            "report_date": "2022-12-31",
            "revenue": 100.0,
            "net_profit": 10.0,
            "roe": 12.0,
            "debt_ratio": 55.0,
        },
    ]
    payload = compute_financial_report_analysis(rows)
    assert payload["as_of"] == "2024-12-31"
    assert payload["latest_report_year"] == 2024
    assert payload["grade"] in {"A", "B", "C", "D"}
    assert payload["score"] is not None
    assert payload["metrics"]["revenue_yoy"] == 0.25
    assert payload["metrics"]["net_profit_yoy"] == 0.5
    assert payload["metrics"]["latest_net_margin"] == 0.12
    assert round(payload["metrics"]["net_margin_change"], 6) == 0.02
    assert payload["series"][0]["report_year"] == 2024
    assert len(payload["highlights"]) >= 4


def test_compute_financial_report_analysis_risk_case() -> None:
    rows = [
        {
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": 90.0,
            "net_profit": 4.0,
            "roe": 6.0,
            "debt_ratio": 75.0,
        },
        {
            "report_year": 2023,
            "report_date": "2023-12-31",
            "revenue": 100.0,
            "net_profit": 10.0,
            "roe": 9.0,
            "debt_ratio": 68.0,
        },
    ]
    payload = compute_financial_report_analysis(rows)
    assert payload["metrics"]["revenue_yoy"] == -0.1
    assert payload["metrics"]["net_profit_yoy"] == -0.6
    assert payload["grade"] in {"C", "D"}
    assert payload["score"] <= 55
    assert any(item["level"] == "risk" for item in payload["highlights"])
