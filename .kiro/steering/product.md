# Product Steering

## Purpose

`investment_assistant` is a FastAPI service for A-share investment research. It aggregates market data, industry cycle indicators, macro indicators, and annual report analysis into API responses that can power a lightweight analysis UI or downstream automation.

## Core User Jobs

- Analyze one stock and inspect cached price plus financial history.
- Analyze a watchlist and compare the latest snapshot for multiple symbols.
- Inspect macro and industry cycle signals without manually stitching sources.
- Analyze annual report data from symbol-based fetches or a supplied report URL.

## Product Priorities

- Prefer useful partial results over all-or-nothing failures when upstream data sources are unstable.
- Preserve predictable response shapes so the frontend and scripts can handle warnings and fallbacks.
- Keep latency acceptable for common research workflows, especially watchlist analysis.
- Make data provenance and freshness understandable when possible.

## Non-Goals

- Real-time trading execution.
- Tick-level market data infrastructure.
- A fully generic portfolio management system.

## Spec Bias

When creating a new spec, favor improvements that strengthen one of these areas:

- reliability under flaky upstream APIs
- latency for analyst-facing endpoints
- observability for cache/fetch fallbacks
- clearer separation between API, usecase, service, and persistence layers
