# Industry Data Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Industry Cycles and External Data results trustworthy by tightening parser validation, making fallback semantics explicit, and surfacing source links and refresh context in the UI.

**Architecture:** Service-layer source adapters remain responsible for fetch/parse/validate behavior. Usecase code owns cache fallback decisions and payload semantics. The frontend renders the normalized row shape without re-encoding source-specific rules.

**Tech Stack:** Python 3.9, FastAPI, SQLite, requests, BeautifulSoup, pytest, plain HTML/JS frontend.

---

### Task 1: Cement index validation

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/services/industry_data_service.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_data_service.py`

- [ ] Write a failing test for suspicious CEMPI placeholder extraction.
- [ ] Run `source .venv/bin/activate && python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_industry_data_service.py -k cempi` and confirm the new test fails.
- [ ] Implement source-specific validation so placeholder-like values are rejected.
- [ ] Re-run the focused test command and confirm it passes.
- [ ] Commit with a parser-validation scoped message.

### Task 2: Thermal coal blocked/cache semantics

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/services/industry_data_service.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/industry_usecase.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_data_service.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_usecase.py`

- [ ] Add failing tests for `Sxcoal` blocked responses with and without compatible cache.
- [ ] Run the focused test command for industry service/usecase and confirm the failures.
- [ ] Implement `blocked`, `cached`, and `stale` behavior for `thermal_coal_index`.
- [ ] Re-run focused tests and confirm they pass.
- [ ] Commit with a fallback-semantics scoped message.

### Task 3: Unified industry payload semantics

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/industry_usecase.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_usecase.py`

- [ ] Add failing tests for industry rows showing cached values with explicit cached/stale statuses.
- [ ] Run `source .venv/bin/activate && python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_industry_usecase.py` and confirm failures.
- [ ] Normalize industry payload rows so status semantics match the design.
- [ ] Re-run the focused test command and confirm it passes.
- [ ] Commit the payload-semantics change.

### Task 4: Industry links and refresh context UI

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`

- [ ] Add failing frontend tests for an Industry `Link` column and a `Refreshed At` display.
- [ ] Run `source .venv/bin/activate && python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_financial_report_frontend.py -k industry` and confirm failures.
- [ ] Implement the UI updates using the normalized payload fields.
- [ ] Re-run the focused frontend test command and confirm it passes.
- [ ] Commit the UI change.

### Task 5: Full reliability regression

**Files:**
- Modify if needed: `/Users/brenda/Projects/investment_assistant/docs/handoff.md`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_data_service.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_industry_usecase.py`
- Test: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`

- [ ] Run the combined focused regression suite.
- [ ] Run `python3 -m compileall /Users/brenda/Projects/investment_assistant/app`.
- [ ] Update handoff notes if code reality changed from the design.
- [ ] Commit the final polish only if needed.
