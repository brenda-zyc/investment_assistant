# Project Handoff

## Project Goal

Build a local A-share investment analysis app with:
- FastAPI backend
- SQLite persistence
- Single-page HTML frontend
- Stock analysis, macro indicators, industry cycle data, and report analysis modules

## Current Architecture

- `/Users/brenda/Projects/investment_assistant/app/main.py`
  - FastAPI app entrypoint and route registration
- `/Users/brenda/Projects/investment_assistant/app/api/`
  - Thin HTTP layer
- `/Users/brenda/Projects/investment_assistant/app/usecases/`
  - Orchestration logic
- `/Users/brenda/Projects/investment_assistant/app/services/`
  - External data fetch, normalization, retry behavior
- `/Users/brenda/Projects/investment_assistant/app/db.py`
  - SQLite schema and persistence helpers
- `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
  - Single-page dashboard UI

## Completed Work

- Split `investment_assistant` into an independent Git repository.
- Built stock analysis, macro indicators, industry cycles, and report analysis views.
- Added bounded concurrent watchlist fetch:
  - max 20 symbols
  - max 4 workers
  - batch realtime/name enrichment after symbol snapshots
- Added SQLite `timeout` and `busy_timeout` to reduce lock contention.
- Added industry cycle diagnostics with `source`, `status`, and `error`.
- Added watchlist tests for:
  - order preservation
  - deduplication
  - worker failure isolation
  - warning path behavior
- Fixed single-stock JSON failure caused by a backend exception path.
- Added watchlist status tooltip behavior:
  - keep `Warning` badge
  - show warning subtypes on hover
- Added repo-level execution docs:
  - `/Users/brenda/Projects/investment_assistant/TESTING.md`
  - `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md`
- Added autonomous annual-report reading workflow:
  - auto-discover latest annual report by symbol
  - extract report-level profit-quality and capex metrics
  - answer three questions on profit authenticity, sustainability, and capital intensity
  - expose `GET /api/financial-report-autoread`
  - render the result inside the Financial Reports panel
- Added explicit auto-read provenance labeling:
  - `current_mode = historical_fallback`
  - `current_mode = report_text_extracted`
- Added DeepSeek-first LLM session support for annual-report auto-read:
  - browser `localStorage` persistence
  - backend in-memory session config
  - session save/status endpoint
  - test-connection endpoint
  - optional `LLM Reading Notes` block in the Financial Reports UI
- Added a standing documentation rule:
  - important architecture, storage, security, provider, and fallback decisions must be recorded under `/Users/brenda/Projects/investment_assistant/docs/decisions/`

## In-Progress Changes

- Modified but not yet committed:
  - `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-03-31-llm-autoread-config.md`
  - `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-03-31-llm-autoread-enhancement.md`
  - `/Users/brenda/Projects/investment_assistant/TESTING.md`
  - `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md`
  - `/Users/brenda/Projects/investment_assistant/docs/thread_workflow.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/financial-report-autoread/requirements.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/financial-report-autoread/design.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/financial-report-autoread/tasks.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/requirements.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/design.md`
  - `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/tasks.md`
  - `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
  - `/Users/brenda/Projects/investment_assistant/app/core_logic.py`
  - `/Users/brenda/Projects/investment_assistant/app/main.py`
  - `/Users/brenda/Projects/investment_assistant/app/services/common.py`
  - `/Users/brenda/Projects/investment_assistant/app/services/financial_report_service.py`
  - `/Users/brenda/Projects/investment_assistant/app/services/llm_service.py`
  - `/Users/brenda/Projects/investment_assistant/app/services/market_data_service.py`
  - `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
  - `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`
  - `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_core_logic.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_usecase.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_llm_service.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_market_usecase.py`
  - `/Users/brenda/Projects/investment_assistant/tests/test_report_text_parser.py`
- Current branch:
  - `main`

## Open Risks

- Upstream DNS and network instability is the main runtime bottleneck.
- Common failing domains include Eastmoney, SSE, and some Sina endpoints.
- Current fallback design improves availability, but not latency.
- New symbols can still be slow because the app tries fresh upstream fetches before settling on cached fallback data.
- `Warning` currently means partial upstream failure with degraded fallback, not complete failure.

## Next Step

Primary recommendation:
- Add DNS preflight and fast-fail logic in market data fetch paths to reduce slow retries.

Secondary recommendation:
- Manually smoke-test `Auto Read Annual Report` on a known symbol once the upstream disclosure endpoints resolve.

Current design work:
- Report Q&A design written at `/Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-01-report-qa-design.md`.
- Matching cc-sdd spec scaffold added under `/Users/brenda/Projects/investment_assistant/.kiro/specs/report-qa/`.
- Next gated step is user review of the written spec before implementation planning.

Current design decision:
- LLM-backed annual-report auto-read will use browser `localStorage` plus backend session-memory configuration.
- See `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-03-31-llm-autoread-config.md`.

Current implementation note:
- `Auto Read Annual Report` now returns source mode and optional LLM interpretation.
- LLM enhancement requires:
  - local browser config
  - explicit `Save for this session`
  - available report text from the fetched annual report

Operational note:
- New threads should also read `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md` when the task is expected to run with minimal user interruption.

## Working Prompt For New Threads

Use this at the top of a new thread:

```text
先读取 /Users/brenda/Projects/investment_assistant/docs/handoff.md 和当前 git diff，再继续当前任务。不要从头设计。
```
