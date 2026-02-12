from __future__ import annotations

import math

import pandas as pd
import pytest

from app.services import market_data_service as market


def test_normalize_stock_code_valid_and_invalid() -> None:
    assert market.normalize_stock_code("600519") == "600519"
    assert market.normalize_stock_code(" 000001 ") == "000001"

    with pytest.raises(ValueError):
        market.normalize_stock_code("ABC123")
    with pytest.raises(ValueError):
        market.normalize_stock_code("60051")


def test_build_revenue_cagr_5y_series_transformation() -> None:
    revenue_points = [
        ("2018-12-30", 100.0),
        ("2019-12-31", 120.0),
        ("2020-12-31", 130.0),
        ("2021-12-31", 140.0),
        ("2022-12-31", 160.0),
        ("2023-12-31", 200.0),
    ]

    series = market.build_revenue_cagr_5y_series(revenue_points)
    assert len(series) == 1
    assert series[0][0] == "2023-12-31"
    expected = math.pow(200.0 / 100.0, 1 / 5) - 1
    assert round(series[0][1], 10) == round(expected, 10)


def test_fetch_price_data_parses_and_filters_rows(monkeypatch) -> None:
    sample_df = pd.DataFrame(
        [
            {"日期": "2024-01-03", "开盘": "10", "收盘": "11", "最高": "11.5", "最低": "9.8", "成交量": "1000", "成交额": "2000"},
            {"日期": "bad-date", "开盘": "10", "收盘": "11"},
            {"日期": "2024-01-02", "开盘": "9", "收盘": "10", "最高": "10.2", "最低": "8.9", "成交量": "800", "成交额": "1500"},
        ]
    )

    def fake_call(_func, *args, **kwargs):  # noqa: ANN001
        assert kwargs["symbol"] == "600519"
        return sample_df

    monkeypatch.setattr(market, "_call_with_resilience", fake_call)

    rows = market.fetch_price_data("600519")
    assert [row["trade_date"] for row in rows] == ["2024-01-02", "2024-01-03"]
    assert rows[0]["open"] == 9.0
    assert rows[1]["close"] == 11.0
