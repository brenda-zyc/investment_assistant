from __future__ import annotations

import time

from app.usecases import market_usecase


def test_analyze_multi_symbols_preserves_order_and_batches_enrichment(monkeypatch) -> None:
    """Watchlist fan-out should preserve input order and batch name/realtime enrichment once."""
    call_log: list[tuple[str, list[str]]] = []

    def fake_worker(symbol: str, *, refresh: bool = False) -> dict:
        delay_map = {"000333": 0.03, "601899": 0.01, "600900": 0.02}
        time.sleep(delay_map[symbol])
        return {
            "symbol": symbol,
            "symbol_name": None,
            "latest_price": {"trade_date": "2026-02-10", "close": 10.0},
            "latest_financial": {"report_year": 2025},
            "close_percentile": 80,
            "realtime": None,
            "warnings": [],
        }

    def fake_fetch_stock_names(symbols: list[str]) -> dict[str, str]:
        call_log.append(("names", list(symbols)))
        return {symbol: f"name-{symbol}" for symbol in symbols}

    def fake_fetch_realtime_quotes(symbols: list[str]) -> dict[str, dict]:
        call_log.append(("realtime", list(symbols)))
        return {
            symbol: {
                "symbol": symbol,
                "name": f"rt-{symbol}",
                "latest_price": 88.0,
                "updated_at": "2026-02-11 09:30:00",
            }
            for symbol in symbols
        }

    monkeypatch.setattr(market_usecase, "_build_watchlist_snapshot", fake_worker)
    monkeypatch.setattr(market_usecase, "fetch_stock_names", fake_fetch_stock_names)
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", fake_fetch_realtime_quotes)

    payload = market_usecase.analyze_multi_symbols(["000333", "601899", "000333", "bad", "600900"])
    results = payload["results"]

    assert [item["symbol"] for item in results] == ["000333", "601899", "bad", "600900"]
    assert results[2]["error"] == "Stock code must be a 6-digit A-share code, e.g. 600519"
    assert [entry for entry in call_log if entry[0] == "names"] == [
        ("names", ["000333", "601899", "600900"])
    ]
    assert [entry for entry in call_log if entry[0] == "realtime"] == [
        ("realtime", ["000333", "601899", "600900"])
    ]
    assert results[0]["symbol_name"] == "rt-000333"
    assert results[0]["latest_price"]["close"] == 88.0
    assert results[0]["latest_price"]["trade_date"] == "2026-02-11 09:30:00"


def test_analyze_multi_symbols_isolates_worker_exceptions(monkeypatch) -> None:
    """One worker failure should produce one error row and keep other symbols flowing."""
    batched_symbols: list[tuple[str, list[str]]] = []

    def fake_worker(symbol: str, *, refresh: bool = False) -> dict:
        if symbol == "600900":
            raise ValueError("sqlite locked")
        return {
            "symbol": symbol,
            "symbol_name": None,
            "latest_price": {"trade_date": "2026-02-10", "close": 20.0},
            "latest_financial": None,
            "close_percentile": 50,
            "realtime": None,
            "warnings": ["cached"],
        }

    def fake_fetch_stock_names(symbols: list[str]) -> dict[str, str]:
        batched_symbols.append(("names", list(symbols)))
        return {}

    def fake_fetch_realtime_quotes(symbols: list[str]) -> dict[str, dict]:
        batched_symbols.append(("realtime", list(symbols)))
        return {}

    monkeypatch.setattr(market_usecase, "_build_watchlist_snapshot", fake_worker)
    monkeypatch.setattr(market_usecase, "fetch_stock_names", fake_fetch_stock_names)
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", fake_fetch_realtime_quotes)

    payload = market_usecase.analyze_multi_symbols(["000333", "600900"])
    results = payload["results"]

    assert results[0]["symbol"] == "000333"
    assert results[1] == {"symbol": "600900", "error": "sqlite locked"}
    assert batched_symbols == [
        ("names", ["000333"]),
        ("realtime", ["000333"]),
    ]


def test_analyze_multi_symbols_deduplicates_before_worker_submission_and_respects_cap(monkeypatch) -> None:
    """Worker submission should use first-seen unique symbols up to the configured cap."""
    submitted_symbols: list[str] = []

    def fake_worker(symbol: str, *, refresh: bool = False) -> dict:
        submitted_symbols.append(symbol)
        return {
            "symbol": symbol,
            "symbol_name": None,
            "latest_price": None,
            "latest_financial": None,
            "close_percentile": None,
            "realtime": None,
            "warnings": [],
        }

    monkeypatch.setattr(market_usecase, "_build_watchlist_snapshot", fake_worker)
    monkeypatch.setattr(market_usecase, "fetch_stock_names", lambda _symbols: {})
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", lambda _symbols: {})

    raw_codes = [f"{i:06d}" for i in range(22)] + ["000001", "000002"]
    payload = market_usecase.analyze_multi_symbols(raw_codes)

    assert len(payload["results"]) == market_usecase.WATCHLIST_MAX_SYMBOLS
    assert submitted_symbols == [f"{i:06d}" for i in range(market_usecase.WATCHLIST_MAX_SYMBOLS)]


def test_analyze_single_symbol_keeps_warning_paths_after_cache_refactor(monkeypatch) -> None:
    """Single-symbol flow should append warning text without crashing when optional feeds fail."""
    monkeypatch.setattr(
        market_usecase,
        "_fetch_cached_symbol_data",
        lambda _symbol, refresh=False: {
            "price_data": [{"trade_date": "2026-03-13", "close": 10.0}],
            "financial_summary": [{"report_year": 2025}],
            "warnings": ["cached data"],
        },
    )

    def raise_name_error(_symbols: list[str]) -> dict[str, str]:
        raise RuntimeError("name source down")

    def raise_realtime_error(_symbols: list[str]) -> dict[str, dict]:
        raise RuntimeError("realtime source down")

    monkeypatch.setattr(market_usecase, "fetch_stock_names", raise_name_error)
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", raise_realtime_error)

    payload = market_usecase.analyze_single_symbol("000333")

    assert payload["symbol"] == "000333"
    assert payload["price_data"][0]["close"] == 10.0
    assert payload["realtime"] is None
    assert payload["warnings"] == [
        "cached data",
        "Stock name fetch failed. Reason: name source down",
        "Realtime quote fetch failed; using historical latest close. Reason: realtime source down",
    ]


def test_analyze_single_symbol_uses_cache_without_network_when_refresh_false(monkeypatch) -> None:
    """Single-symbol analysis should reuse cache unless the caller explicitly refreshes."""
    monkeypatch.setattr(
        market_usecase,
        "fetch_stock_prices",
        lambda symbol: [{"trade_date": "2026-04-09", "close": 10.0}],
    )
    monkeypatch.setattr(
        market_usecase,
        "fetch_financial_reports",
        lambda symbol: [{"report_year": 2025, "report_date": "2025-12-31"}],
    )

    def fail_price_fetch(_symbol: str):
        raise AssertionError("network fetch should not run")

    def fail_financial_fetch(_symbol: str):
        raise AssertionError("network fetch should not run")

    monkeypatch.setattr(market_usecase, "fetch_price_data", fail_price_fetch)
    monkeypatch.setattr(market_usecase, "fetch_financial_summary", fail_financial_fetch)
    monkeypatch.setattr(market_usecase, "fetch_stock_names", lambda _symbols: {})
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", lambda _symbols: {})

    payload = market_usecase.analyze_single_symbol("000333", refresh=False)

    assert payload["price_data"] == [{"trade_date": "2026-04-09", "close": 10.0}]
    assert payload["financial_summary"] == [{"report_year": 2025, "report_date": "2025-12-31"}]
    assert payload["warnings"] == []


def test_analyze_multi_symbols_forwards_refresh_to_worker(monkeypatch) -> None:
    """Watchlist analysis should pass the explicit refresh flag down to each worker call."""
    submitted: list[tuple[str, bool]] = []

    def fake_worker(symbol: str, *, refresh: bool = False) -> dict:
        submitted.append((symbol, refresh))
        return {
            "symbol": symbol,
            "symbol_name": None,
            "latest_price": None,
            "latest_financial": None,
            "close_percentile": None,
            "realtime": None,
            "warnings": [],
        }

    monkeypatch.setattr(market_usecase, "_build_watchlist_snapshot", fake_worker)
    monkeypatch.setattr(market_usecase, "fetch_stock_names", lambda _symbols: {})
    monkeypatch.setattr(market_usecase, "fetch_realtime_quotes", lambda _symbols: {})

    market_usecase.analyze_multi_symbols(["000333", "600900"], refresh=True)

    assert submitted == [("000333", True), ("600900", True)]
