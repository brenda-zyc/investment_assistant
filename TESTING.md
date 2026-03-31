# Testing Guide

## Purpose

Provide one stable place for automated and manual verification commands so new threads can validate changes without depending on old chat history.

## Environment

Run all commands from:

```bash
cd /Users/brenda/Projects/investment_assistant
source .venv/bin/activate
```

## Default Automated Check

Use this as the stable default regression command in this environment:

```bash
python -m pytest -p no:cov -q --override-ini addopts=''
```

Reason:
- avoids the local `pytest-cov` CPU spike issue described in `/Users/brenda/Projects/investment_assistant/TIPS.md`
- gives a fast functional signal without depending on coverage tooling stability

## Targeted Test Commands

Run a single module when a change is localized:

```bash
python -m pytest -p no:cov -q --override-ini addopts='' tests/test_market_usecase.py
python -m pytest -p no:cov -q --override-ini addopts='' tests/test_market_data_service.py
python -m pytest -p no:cov -q --override-ini addopts='' tests/test_industry_data_service.py
python -m pytest -p no:cov -q --override-ini addopts='' tests/test_core_logic.py
python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_text_parser.py
```

## Manual Smoke Test

Start the app:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Single Stock

Use `000333` as the baseline manual test symbol.

Check:
- page loads without frontend JSON parse errors
- stock analysis returns price rows
- financial summary table renders
- metrics panel renders without layout break

### Watchlist

Use:

```text
000333, 601899, 600900
```

Check:
- rows return in input order
- duplicates are removed
- one bad symbol does not break the full request
- status badge renders as `OK`, `Warning`, or `Error`
- hovering `Warning` shows warning subtype detail

### Macro Indicators

Check:
- selected table loads rows
- signal panel renders
- valuation panel renders
- empty table states are explicit, not silent

### Industry Cycles

Check:
- rows render
- grouped sections remain readable
- `source`, `status`, and `error` fields are coherent when upstream data is missing

### Report Analysis

Check:
- report load request returns JSON
- highlights and evidence render
- table rows remain aligned after a failed request or retry

## Known Environment Risks

### Network and DNS

This project depends on upstream sources that are sometimes unstable in the current environment.

Common symptoms:
- slow watchlist responses
- fallback warnings
- missing realtime quotes
- partial data loads

Commonly affected domains include:
- Eastmoney endpoints
- SSE endpoints
- Sina endpoints

Interpretation:
- `Warning` usually means partial upstream failure with cached or degraded fallback
- `Error` usually means the row or request could not complete its primary goal

### macOS Local Tooling

`pytest-cov` can trigger high CPU usage via `syspolicyd` and `trustd`.

Use the no-coverage pytest command above unless full coverage is explicitly required.

## Validation Expectations Per Task

For each implementation stage:

1. Run the smallest relevant automated test set.
2. Run a manual smoke test only for affected surfaces.
3. Record what was verified and what could not be verified.
4. If upstream network instability prevents a clean check, state that explicitly instead of assuming success.

## TODO

- Add a release-focused smoke checklist once deployment flow is stable.
- Add fixture-based offline checks for network-sensitive paths where practical.
