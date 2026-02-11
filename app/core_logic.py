from __future__ import annotations

from typing import Any, Callable


def to_float(value: object) -> float | None:
    """Convert raw value into float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_latest_close_percentile(price_rows: list[dict]) -> int | None:
    """Compute percentile of latest close within stored close history."""
    if not price_rows:
        return None

    closes: list[float] = []
    latest_close: float | None = None
    for row in price_rows:
        value = to_float(row.get("close"))
        if value is None:
            continue
        closes.append(value)
        if latest_close is None:
            latest_close = value

    if latest_close is None or len(closes) < 2:
        return None

    rank_le = sum(1 for value in closes if value <= latest_close)
    percentile = int(round((rank_le / len(closes)) * 100))
    return max(0, min(100, percentile))


def compute_percentile_from_points(points: list[tuple[str, float]], min_samples: int = 24) -> dict:
    """Compute latest-value percentile within a metric's historical series."""
    # Data cleaning rule: ignore null values before percentile ranking.
    cleaned = [(d, v) for d, v in points if v is not None]
    if not cleaned:
        return {"value": None, "percentile": None, "as_of": None, "data_insufficient": True, "sample_size": 0}

    latest_date, latest_value = cleaned[-1]
    series_values = [v for _, v in cleaned]
    sample_size = len(series_values)
    if sample_size < min_samples:
        return {
            "value": latest_value,
            "percentile": None,
            "as_of": latest_date,
            "data_insufficient": True,
            "sample_size": sample_size,
        }

    # Percentile logic: rank latest observation in its own historical distribution.
    rank_le = sum(1 for value in series_values if value <= latest_value)
    percentile = int(round((rank_le / sample_size) * 100))
    percentile = max(0, min(100, percentile))
    return {
        "value": latest_value,
        "percentile": percentile,
        "as_of": latest_date,
        "data_insufficient": False,
        "sample_size": sample_size,
    }


def signal_from_percentile(percentile: int) -> tuple[str, str]:
    """Map percentile to valuation-style signal label and color."""
    if percentile < 20:
        return ("Undervalued", "green")
    if percentile <= 60:
        return ("Neutral", "yellow")
    return ("Expensive", "red")


def compute_macro_signals(rows: list[dict]) -> list[dict]:
    """Compute percentile-based macro signals using full available history."""
    if not rows:
        return []

    indicators = [key for key in rows[0].keys() if key != "date"]
    signals: list[dict] = []

    for indicator in indicators:
        latest_value: float | None = None
        series: list[float] = []

        for row in rows:
            value = to_float(row.get(indicator))
            if value is not None:
                series.append(value)
                if latest_value is None:
                    latest_value = value

        if latest_value is None or not series:
            continue

        # Percentile logic: compare latest value against the metric's own history.
        less_or_equal_count = sum(1 for value in series if value <= latest_value)
        percentile = int(round((less_or_equal_count / len(series)) * 100))
        percentile = max(0, min(100, percentile))
        # Financial rule override: PMI uses an economic threshold, not valuation buckets.
        if indicator == "china_pmi":
            if latest_value >= 50:
                signal_label, signal_color = ("Expansion", "green")
            else:
                signal_label, signal_color = ("Contraction", "red")
        else:
            signal_label, signal_color = signal_from_percentile(percentile)

        signals.append(
            {
                "indicator": indicator,
                "value": latest_value,
                "percentile": percentile,
                "signal_label": signal_label,
                "signal_color": signal_color,
            }
        )

    return sorted(signals, key=lambda item: item["indicator"])


def compute_stock_metrics(
    symbol: str,
    fetch_valuation_series_fn: Callable[[str], dict[str, list[tuple[str, float]]]],
    fetch_financial_metric_series_fn: Callable[[str], dict[str, list[tuple[str, float]]]],
    build_revenue_cagr_5y_series_fn: Callable[[list[tuple[str, float]]], list[tuple[str, float]]],
    warn_fn: Callable[[str, str, Exception], None] | None = None,
) -> dict:
    """Build stock metric payload with value/percentile and sampling metadata."""
    # API assumption: upstream AkShare endpoints can fail independently.
    try:
        valuation_series = fetch_valuation_series_fn(symbol)
    except Exception as exc:
        if warn_fn:
            warn_fn("valuation", symbol, exc)
        valuation_series = {"pe_ttm": [], "pb": []}

    try:
        fin_series = fetch_financial_metric_series_fn(symbol)
    except Exception as exc:
        if warn_fn:
            warn_fn("financial", symbol, exc)
        fin_series = {"roe": [], "roic": [], "revenue": []}

    # Financial logic: CAGR is derived from revenue history, not fetched directly.
    revenue_cagr_series = build_revenue_cagr_5y_series_fn(fin_series.get("revenue", []))

    metric_sources = {
        "pe_ttm": valuation_series.get("pe_ttm", []),
        "pb": valuation_series.get("pb", []),
        "roe": fin_series.get("roe", []),
        "roic": fin_series.get("roic", []),
        "revenue_cagr_5y": revenue_cagr_series,
    }
    metric_units = {
        "pe_ttm": "",
        "pb": "",
        "roe": "ratio",
        "roic": "ratio",
        "revenue_cagr_5y": "ratio",
    }

    metrics_payload: list[dict[str, Any]] = []
    as_of_dates: list[str] = []
    for metric_name, points in metric_sources.items():
        computed = compute_percentile_from_points(points, min_samples=24)
        if computed["as_of"]:
            as_of_dates.append(computed["as_of"])
        metrics_payload.append(
            {
                "name": metric_name,
                "value": computed["value"],
                "percentile": computed["percentile"],
                "unit": metric_units[metric_name],
                "data_insufficient": computed["data_insufficient"],
                "sample_size": computed["sample_size"],
            }
        )

    # TODO: support alternate percentile windows for custom research scenarios.
    return {
        "symbol": symbol,
        "as_of": max(as_of_dates) if as_of_dates else None,
        "metrics": metrics_payload,
    }


def _compute_yoy(latest: float | None, previous: float | None) -> float | None:
    """Compute year-over-year growth ratio."""
    if latest is None or previous is None or previous == 0:
        return None
    return (latest - previous) / abs(previous)


def _compute_cagr(points: list[tuple[int, float | None]]) -> float | None:
    """Compute CAGR from yearly points (year, value)."""
    valid = [(year, value) for year, value in points if value is not None and value > 0]
    if len(valid) < 2:
        return None
    start_year, start_value = valid[0]
    end_year, end_value = valid[-1]
    year_span = end_year - start_year
    if year_span <= 0:
        return None
    return (end_value / start_value) ** (1 / year_span) - 1


def compute_financial_report_analysis(financial_rows: list[dict]) -> dict:
    """Build financial-report analysis payload for UI consumption."""
    cleaned_rows: list[dict] = []
    for row in financial_rows:
        try:
            report_year = int(row.get("report_year"))
        except (TypeError, ValueError):
            continue
        cleaned_rows.append(
            {
                "report_year": report_year,
                "report_date": row.get("report_date"),
                "revenue": to_float(row.get("revenue")),
                "net_profit": to_float(row.get("net_profit")),
                "roe": to_float(row.get("roe")),
                "debt_ratio": to_float(row.get("debt_ratio")),
            }
        )

    if not cleaned_rows:
        return {
            "as_of": None,
            "latest_report_year": None,
            "score": None,
            "grade": None,
            "metrics": {
                "revenue": None,
                "net_profit": None,
                "roe": None,
                "debt_ratio": None,
                "revenue_yoy": None,
                "net_profit_yoy": None,
                "revenue_cagr": None,
                "net_profit_cagr": None,
                "latest_net_margin": None,
                "net_margin_change": None,
            },
            "highlights": [{"level": "info", "title": "No financial data", "detail": "No report rows available."}],
            "series": [],
        }

    asc_rows = sorted(cleaned_rows, key=lambda item: item["report_year"])
    desc_rows = list(reversed(asc_rows))
    latest = desc_rows[0]
    previous = desc_rows[1] if len(desc_rows) > 1 else None

    revenue_yoy = _compute_yoy(latest["revenue"], previous["revenue"] if previous else None)
    net_profit_yoy = _compute_yoy(latest["net_profit"], previous["net_profit"] if previous else None)

    revenue_cagr = _compute_cagr([(row["report_year"], row["revenue"]) for row in asc_rows])
    net_profit_cagr = _compute_cagr([(row["report_year"], row["net_profit"]) for row in asc_rows])

    latest_margin = None
    previous_margin = None
    if latest["revenue"] not in (None, 0) and latest["net_profit"] is not None:
        latest_margin = latest["net_profit"] / latest["revenue"]
    if previous and previous["revenue"] not in (None, 0) and previous["net_profit"] is not None:
        previous_margin = previous["net_profit"] / previous["revenue"]
    margin_change = None
    if latest_margin is not None and previous_margin is not None:
        margin_change = latest_margin - previous_margin

    score = 50
    if revenue_yoy is not None:
        score += 20 if revenue_yoy > 0 else -15
    if net_profit_yoy is not None:
        score += 20 if net_profit_yoy > 0 else -20
    if latest["roe"] is not None:
        if latest["roe"] >= 15:
            score += 15
        elif latest["roe"] >= 8:
            score += 5
        else:
            score -= 10
    if latest["debt_ratio"] is not None:
        if latest["debt_ratio"] < 50:
            score += 10
        elif latest["debt_ratio"] > 70:
            score -= 15
    if margin_change is not None:
        score += 10 if margin_change > 0 else -5

    score = max(0, min(100, score))
    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 55:
        grade = "C"
    else:
        grade = "D"

    highlights: list[dict[str, str]] = []
    if revenue_yoy is None:
        highlights.append(
            {"level": "info", "title": "Revenue trend", "detail": "Insufficient data to compute YoY revenue growth."}
        )
    elif revenue_yoy >= 0:
        highlights.append(
            {
                "level": "ok",
                "title": "Revenue trend",
                "detail": f"Latest revenue is up {revenue_yoy * 100:.2f}% YoY.",
            }
        )
    else:
        highlights.append(
            {
                "level": "risk",
                "title": "Revenue trend",
                "detail": f"Latest revenue is down {abs(revenue_yoy) * 100:.2f}% YoY.",
            }
        )

    if net_profit_yoy is None:
        highlights.append(
            {"level": "info", "title": "Profit trend", "detail": "Insufficient data to compute YoY net profit growth."}
        )
    elif net_profit_yoy >= 0:
        highlights.append(
            {
                "level": "ok",
                "title": "Profit trend",
                "detail": f"Latest net profit is up {net_profit_yoy * 100:.2f}% YoY.",
            }
        )
    else:
        highlights.append(
            {
                "level": "risk",
                "title": "Profit trend",
                "detail": f"Latest net profit is down {abs(net_profit_yoy) * 100:.2f}% YoY.",
            }
        )

    if latest["roe"] is None:
        highlights.append({"level": "info", "title": "ROE quality", "detail": "ROE is missing in latest report."})
    elif latest["roe"] >= 15:
        highlights.append(
            {"level": "ok", "title": "ROE quality", "detail": f"ROE is {latest['roe']:.2f}%, indicating strong capital return."}
        )
    elif latest["roe"] >= 8:
        highlights.append(
            {"level": "warn", "title": "ROE quality", "detail": f"ROE is {latest['roe']:.2f}%, in a neutral range."}
        )
    else:
        highlights.append(
            {
                "level": "risk",
                "title": "ROE quality",
                "detail": f"ROE is {latest['roe']:.2f}%, which may indicate weak profitability quality.",
            }
        )

    if latest["debt_ratio"] is None:
        highlights.append({"level": "info", "title": "Leverage risk", "detail": "Debt ratio is missing in latest report."})
    elif latest["debt_ratio"] > 70:
        highlights.append(
            {
                "level": "risk",
                "title": "Leverage risk",
                "detail": f"Debt ratio is {latest['debt_ratio']:.2f}%, leverage risk is elevated.",
            }
        )
    elif latest["debt_ratio"] >= 50:
        highlights.append(
            {
                "level": "warn",
                "title": "Leverage risk",
                "detail": f"Debt ratio is {latest['debt_ratio']:.2f}%, leverage is moderate.",
            }
        )
    else:
        highlights.append(
            {
                "level": "ok",
                "title": "Leverage risk",
                "detail": f"Debt ratio is {latest['debt_ratio']:.2f}%, balance sheet appears conservative.",
            }
        )

    return {
        "as_of": latest.get("report_date"),
        "latest_report_year": latest["report_year"],
        "score": score,
        "grade": grade,
        "metrics": {
            "revenue": latest["revenue"],
            "net_profit": latest["net_profit"],
            "roe": latest["roe"],
            "debt_ratio": latest["debt_ratio"],
            "revenue_yoy": revenue_yoy,
            "net_profit_yoy": net_profit_yoy,
            "revenue_cagr": revenue_cagr,
            "net_profit_cagr": net_profit_cagr,
            "latest_net_margin": latest_margin,
            "net_margin_change": margin_change,
        },
        "highlights": highlights,
        "series": desc_rows,
    }
