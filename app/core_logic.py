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


def _latest_value_from_points(points: list[tuple[str, float]] | None) -> tuple[str | None, float | None]:
    """Return the latest point from an ascending date/value series."""
    if not points:
        return None, None
    latest_date, latest_value = points[-1]
    return latest_date, latest_value


def _previous_value_from_points(points: list[tuple[str, float]] | None) -> tuple[str | None, float | None]:
    """Return the previous point from an ascending date/value series."""
    if not points or len(points) < 2:
        return None, None
    previous_date, previous_value = points[-2]
    return previous_date, previous_value


def _series_cagr(points: list[tuple[str, float]] | None) -> float | None:
    """Compute CAGR from an ascending date/value series using year buckets."""
    if not points:
        return None
    yearly_points: list[tuple[int, float | None]] = []
    for date_text, value in points:
        try:
            year = int(str(date_text)[:4])
        except (TypeError, ValueError):
            continue
        yearly_points.append((year, value))
    return _compute_cagr(yearly_points)


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Return numerator/denominator when both values are valid and denominator is non-zero."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _answer_item(
    *,
    question_id: str,
    question: str,
    verdict: str,
    level: str,
    summary: str,
    evidence: list[str],
    score: int | None = None,
) -> dict[str, Any]:
    """Build one stable answer payload for the autonomous report-read workflow."""
    return {
        "id": question_id,
        "question": question,
        "verdict": verdict,
        "level": level,
        "summary": summary,
        "evidence": evidence,
        "score": score,
    }


def compute_financial_report_autoread_assessment(
    latest_report_metrics: dict[str, Any] | None,
    historical_context: dict[str, list[tuple[str, float]]] | None,
) -> dict[str, Any]:
    """Compute three evidence-backed answers for autonomous annual-report reading."""
    latest_report_metrics = latest_report_metrics or {}
    historical_context = historical_context or {}

    revenue_points = historical_context.get("revenue", [])
    net_profit_points = historical_context.get("net_profit", [])
    roe_points = historical_context.get("roe", [])
    deducted_points = historical_context.get("deducted_net_profit", [])
    operating_cash_flow_points = historical_context.get("operating_cash_flow", [])
    capex_points = historical_context.get("capex_cash_outflow", [])

    _, revenue_latest = _latest_value_from_points(revenue_points)
    _, revenue_previous = _previous_value_from_points(revenue_points)
    _, net_profit_latest = _latest_value_from_points(net_profit_points)
    _, net_profit_previous = _previous_value_from_points(net_profit_points)
    _, roe_latest = _latest_value_from_points(roe_points)
    _, deducted_latest = _latest_value_from_points(deducted_points)
    _, operating_cash_flow_latest = _latest_value_from_points(operating_cash_flow_points)
    _, capex_latest = _latest_value_from_points(capex_points)

    report_revenue = to_float(latest_report_metrics.get("revenue"))
    report_net_profit = to_float(latest_report_metrics.get("net_profit"))
    report_roe = to_float(latest_report_metrics.get("roe"))
    report_deducted_net_profit = to_float(latest_report_metrics.get("deducted_net_profit"))
    report_operating_cash_flow = to_float(latest_report_metrics.get("operating_cash_flow"))
    report_capex = to_float(latest_report_metrics.get("capex_cash_outflow"))

    revenue_latest = report_revenue if report_revenue is not None else revenue_latest
    net_profit_latest = report_net_profit if report_net_profit is not None else net_profit_latest
    roe_latest = report_roe if report_roe is not None else roe_latest
    deducted_latest = report_deducted_net_profit if report_deducted_net_profit is not None else deducted_latest
    operating_cash_flow_latest = (
        report_operating_cash_flow if report_operating_cash_flow is not None else operating_cash_flow_latest
    )
    capex_latest = report_capex if report_capex is not None else capex_latest

    cash_conversion = _safe_ratio(operating_cash_flow_latest, net_profit_latest)
    recurring_profit_ratio = _safe_ratio(deducted_latest, net_profit_latest)
    revenue_yoy = _compute_yoy(revenue_latest, revenue_previous)
    net_profit_yoy = _compute_yoy(net_profit_latest, net_profit_previous)
    revenue_cagr = _series_cagr(revenue_points)
    net_profit_cagr = _series_cagr(net_profit_points)
    capex_revenue_ratio = _safe_ratio(capex_latest, revenue_latest)
    capex_ocf_ratio = _safe_ratio(capex_latest, operating_cash_flow_latest)

    answers: list[dict[str, Any]] = []

    authenticity_evidence: list[str] = []
    authenticity_score = 50
    authenticity_signal_count = 0
    if net_profit_latest is None:
        answers.append(
            _answer_item(
                question_id="profit_authenticity",
                question="这家企业净利润是否为真？",
                verdict="数据不足",
                level="info",
                summary="缺少净利润基准数据，无法判断利润真实性。",
                evidence=["未取得可用的净利润数据。"],
                score=None,
            )
        )
    else:
        if cash_conversion is not None:
            authenticity_signal_count += 1
            authenticity_evidence.append(f"经营现金流/净利润 = {cash_conversion:.2f}x。")
            # Financial logic: cash conversion is a direct check on whether accounting profit is backed by cash.
            if operating_cash_flow_latest <= 0:
                authenticity_score -= 20
            elif cash_conversion >= 1.0:
                authenticity_score += 20
            elif cash_conversion >= 0.8:
                authenticity_score += 10
            elif cash_conversion < 0.5:
                authenticity_score -= 15
        else:
            authenticity_evidence.append("缺少经营现金流与净利润配比数据。")

        if recurring_profit_ratio is not None:
            authenticity_signal_count += 1
            authenticity_evidence.append(f"扣非净利润/净利润 = {recurring_profit_ratio:.2f}x。")
            # Financial logic: a low deducted-profit ratio suggests profit may rely on non-recurring items.
            if recurring_profit_ratio >= 0.9:
                authenticity_score += 20
            elif recurring_profit_ratio >= 0.75:
                authenticity_score += 10
            elif recurring_profit_ratio < 0.5:
                authenticity_score -= 20
            elif recurring_profit_ratio < 0.75:
                authenticity_score -= 5
        else:
            authenticity_evidence.append("缺少扣非净利润对照数据。")

        if authenticity_signal_count == 0:
            answers.append(
                _answer_item(
                    question_id="profit_authenticity",
                    question="这家企业净利润是否为真？",
                    verdict="数据不足",
                    level="info",
                    summary="缺少经营现金流和扣非净利润两个关键对照项，无法稳健判断利润真实性。",
                    evidence=authenticity_evidence,
                    score=None,
                )
            )
        elif authenticity_score >= 70:
            answers.append(
                _answer_item(
                    question_id="profit_authenticity",
                    question="这家企业净利润是否为真？",
                    verdict="较为真实",
                    level="ok",
                    summary="利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    evidence=authenticity_evidence,
                    score=authenticity_score,
                )
            )
        elif authenticity_score >= 45:
            answers.append(
                _answer_item(
                    question_id="profit_authenticity",
                    question="这家企业净利润是否为真？",
                    verdict="基本真实但需跟踪",
                    level="warn",
                    summary="利润未出现明显失真信号，但现金兑现或扣非质量仍需持续跟踪。",
                    evidence=authenticity_evidence,
                    score=authenticity_score,
                )
            )
        else:
            answers.append(
                _answer_item(
                    question_id="profit_authenticity",
                    question="这家企业净利润是否为真？",
                    verdict="存在疑点",
                    level="risk",
                    summary="利润与现金流或扣非口径偏离较大，需警惕利润质量问题。",
                    evidence=authenticity_evidence,
                    score=authenticity_score,
                )
            )

    sustainability_evidence: list[str] = []
    sustainability_score = 50
    sustainability_signal_count = 0
    if revenue_cagr is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"收入 CAGR = {revenue_cagr * 100:.2f}%。")
        if revenue_cagr >= 0.08:
            sustainability_score += 15
        elif revenue_cagr >= 0:
            sustainability_score += 5
        else:
            sustainability_score -= 15
    else:
        sustainability_evidence.append("缺少收入长期趋势数据。")

    if net_profit_cagr is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"净利润 CAGR = {net_profit_cagr * 100:.2f}%。")
        if net_profit_cagr >= 0.08:
            sustainability_score += 20
        elif net_profit_cagr >= 0:
            sustainability_score += 8
        else:
            sustainability_score -= 20
    else:
        sustainability_evidence.append("缺少净利润长期趋势数据。")

    if revenue_yoy is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"最新收入同比 = {revenue_yoy * 100:.2f}%。")
        if revenue_yoy < 0:
            sustainability_score -= 10
    if net_profit_yoy is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"最新净利润同比 = {net_profit_yoy * 100:.2f}%。")
        if net_profit_yoy < 0:
            sustainability_score -= 15

    if roe_latest is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"最新 ROE = {roe_latest:.2f}%。")
        if roe_latest >= 15:
            sustainability_score += 10
        elif roe_latest >= 8:
            sustainability_score += 5
        else:
            sustainability_score -= 10
    else:
        sustainability_evidence.append("缺少最新 ROE 数据。")

    if operating_cash_flow_latest is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"最新经营现金流 = {operating_cash_flow_latest:.2f}。")
        if operating_cash_flow_latest > 0:
            sustainability_score += 5
        else:
            sustainability_score -= 10

    if recurring_profit_ratio is not None:
        sustainability_signal_count += 1
        sustainability_evidence.append(f"最新扣非净利润/净利润 = {recurring_profit_ratio:.2f}x。")
        if recurring_profit_ratio >= 0.8:
            sustainability_score += 5
        elif recurring_profit_ratio < 0.6:
            sustainability_score -= 10

    if sustainability_signal_count == 0:
        answers.append(
            _answer_item(
                question_id="profit_sustainability",
                question="净利润是否可持续？",
                verdict="数据不足",
                level="info",
                summary="缺少多年度经营趋势和质量数据，无法判断利润可持续性。",
                evidence=sustainability_evidence,
                score=None,
            )
        )
    elif sustainability_score >= 70:
        answers.append(
            _answer_item(
                question_id="profit_sustainability",
                question="净利润是否可持续？",
                verdict="较可持续",
                level="ok",
                summary="收入、利润和资本回报率信号整体稳定，利润延续性较强。",
                evidence=sustainability_evidence,
                score=sustainability_score,
            )
        )
    elif sustainability_score >= 45:
        answers.append(
            _answer_item(
                question_id="profit_sustainability",
                question="净利润是否可持续？",
                verdict="一般",
                level="warn",
                summary="利润具备一定延续性，但经营趋势或质量信号仍有波动。",
                evidence=sustainability_evidence,
                score=sustainability_score,
            )
        )
    else:
        answers.append(
            _answer_item(
                question_id="profit_sustainability",
                question="净利润是否可持续？",
                verdict="可持续性偏弱",
                level="risk",
                summary="多年度趋势或利润质量信号较弱，利润持续性需要谨慎看待。",
                evidence=sustainability_evidence,
                score=sustainability_score,
            )
        )

    capital_evidence: list[str] = []
    capital_signal_count = 0
    if capex_revenue_ratio is not None:
        capital_signal_count += 1
        capital_evidence.append(f"资本开支/收入 = {capex_revenue_ratio * 100:.2f}%。")
    else:
        capital_evidence.append("缺少资本开支/收入配比数据。")
    if capex_ocf_ratio is not None:
        capital_signal_count += 1
        capital_evidence.append(f"资本开支/经营现金流 = {capex_ocf_ratio * 100:.2f}%。")
    else:
        capital_evidence.append("缺少资本开支/经营现金流配比数据。")

    if capital_signal_count == 0:
        answers.append(
            _answer_item(
                question_id="capital_intensity",
                question="维持当前状态是否需要大量资本投入？",
                verdict="数据不足",
                level="info",
                summary="缺少资本开支数据，无法判断资本投入强度。",
                evidence=capital_evidence,
                score=None,
            )
        )
    elif (
        (capex_revenue_ratio is not None and capex_revenue_ratio >= 0.15)
        or (capex_ocf_ratio is not None and capex_ocf_ratio >= 0.8)
    ):
        answers.append(
            _answer_item(
                question_id="capital_intensity",
                question="维持当前状态是否需要大量资本投入？",
                verdict="需要较大资本投入",
                level="risk",
                summary="资本开支占收入或经营现金流的比例偏高，维持当前经营状态需要较重再投资。",
                evidence=capital_evidence,
                score=80,
            )
        )
    elif (
        (capex_revenue_ratio is not None and capex_revenue_ratio >= 0.05)
        or (capex_ocf_ratio is not None and capex_ocf_ratio >= 0.3)
    ):
        answers.append(
            _answer_item(
                question_id="capital_intensity",
                question="维持当前状态是否需要大量资本投入？",
                verdict="资本投入中等",
                level="warn",
                summary="维持经营需要一定再投资，但资本压力暂未达到很重的水平。",
                evidence=capital_evidence,
                score=55,
            )
        )
    else:
        answers.append(
            _answer_item(
                question_id="capital_intensity",
                question="维持当前状态是否需要大量资本投入？",
                verdict="资本投入压力较低",
                level="ok",
                summary="资本开支相对收入和经营现金流的占比不高，资本投入压力较轻。",
                evidence=capital_evidence,
                score=25,
            )
        )

    return {
        "answers": answers,
        "derived_metrics": {
            "cash_conversion": cash_conversion,
            "recurring_profit_ratio": recurring_profit_ratio,
            "revenue_yoy": revenue_yoy,
            "net_profit_yoy": net_profit_yoy,
            "revenue_cagr": revenue_cagr,
            "net_profit_cagr": net_profit_cagr,
            "capex_revenue_ratio": capex_revenue_ratio,
            "capex_ocf_ratio": capex_ocf_ratio,
        },
    }


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
