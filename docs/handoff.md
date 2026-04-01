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
- Implemented report-scoped Q&A in the `codex/report-qa` worktree:
  - in-memory report-context cache keyed by `report_key`
  - bounded Q&A history with frontend-owned transcript state
  - `POST /api/financial-report-qa`
  - inline `Ask the Report` panel with guided question chips
  - automatic Q&A session reset when the active report changes
  - separated commits:
    - `27b3e94` `feat(report-qa): cache active report contexts`
    - `5772138` `fix(report-qa): harden report context cache`
    - `d43bacd` `feat(report-qa): add bounded answer modes and llm wrapper`
    - `a304b5a` `fix(report-qa): broaden report-scoped fallback handling`
    - `be61c5d` `feat(report-qa): add api and usecase orchestration`
    - `fa632e9` `feat(report-qa): add inline ask-the-report ui`
- Added a standing documentation rule:
  - important architecture, storage, security, provider, and fallback decisions must be recorded under `/Users/brenda/Projects/investment_assistant/docs/decisions/`

## In-Progress Changes
- Current active implementation branch:
  - `codex/report-qa` in `/Users/brenda/Projects/investment_assistant/.worktrees/report-qa`

## Open Risks

- Upstream DNS and network instability is the main runtime bottleneck.
- Common failing domains include Eastmoney, SSE, and some Sina endpoints.
- Current fallback design improves availability, but not latency.
- New symbols can still be slow because the app tries fresh upstream fetches before settling on cached fallback data.
- `Warning` currently means partial upstream failure with degraded fallback, not complete failure.
- Report-Q&A scope detection is still heuristic. It now rejects obvious market-data questions, but unusual phrasing may still need future tightening.
- `Load Financial Report` still leaves Q&A disabled by design because that path does not load report text.

## Next Step

Primary recommendation:
- Add DNS preflight and fast-fail logic in market data fetch paths to reduce slow retries.

Secondary recommendation:
- Manually smoke-test report Q&A on at least two symbols once the `codex/report-qa` branch is running locally.

Suggested smoke path:
- `000333` -> `Auto Read Annual Report` -> ask one guided question -> verify answer/evidence/citations render
- switch to `600900` -> verify the transcript resets immediately and starts a fresh session

Current design work:
- Report Q&A design written at `/Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-01-report-qa-design.md`.
- Matching cc-sdd spec scaffold added under `/Users/brenda/Projects/investment_assistant/.kiro/specs/report-qa/`.
- Implementation plan saved at `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-01-report-qa.md`.
- Report Q&A implementation will use an in-memory report-context cache keyed by `report_key`; chat transcript remains frontend-only.

Current design decision:
- LLM-backed annual-report auto-read will use browser `localStorage` plus backend session-memory configuration.
- See `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-03-31-llm-autoread-config.md`.

Current implementation note:
- `Auto Read Annual Report` now returns source mode and optional LLM interpretation.
- LLM enhancement requires:
  - local browser config
  - explicit `Save for this session`
  - available report text from the fetched annual report
- Report-Q&A backend/frontend verification completed in the worktree with:
  - `77 passed`
  - `python3 -m compileall app`

Operational note:
- New threads should also read `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md` when the task is expected to run with minimal user interruption.

## Working Prompt For New Threads

Use this at the top of a new thread:

```text
先读取 /Users/brenda/Projects/investment_assistant/docs/handoff.md 和当前 git diff，再继续当前任务。不要从头设计。
```
