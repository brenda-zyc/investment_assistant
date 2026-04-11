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
  - initial in-memory report-context cache keyed by `report_key`
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
- Completed Version B mainflow stability work:
  - added SQLite `report_artifacts` storage in `/Users/brenda/Projects/investment_assistant/app/db.py`
  - made single-stock analysis, watchlist analysis, and financial-report summary cache-first by default
  - added explicit `refresh` / `force_refresh` route controls
  - persisted `Auto Read Annual Report` and report-URL parsing results into SQLite-backed artifacts
  - made report Q&A reload report context from SQLite artifacts when process memory is empty
  - updated the Financial Reports UI so cached reads and explicit refresh actions are separate
  - clarified report-URL helper copy to official-disclosure-only
  - verification completed with:
    - `85 passed` on focused Version B regression modules
    - `187 passed` on the full repo suite
    - `python -m compileall app`

## In-Progress Changes
- No known partial code changes are intentionally left open for Version B.
- Manual browser smoke-testing of the new explicit refresh flows is still recommended.

## Open Risks

- Upstream DNS and network instability is the main runtime bottleneck.
- Common failing domains include Eastmoney, SSE, and some Sina endpoints.
- Cache-first defaults now improve latency for cached symbols, but cache misses and explicit refresh flows still depend on upstream stability.
- `Warning` currently means partial upstream failure with degraded fallback, not complete failure.
- Report-Q&A scope detection is still heuristic. It now rejects obvious market-data questions, but unusual phrasing may still need future tightening.
- `Load Financial Report` still leaves Q&A disabled by design because that path does not load report text.
- LLM session config is still backend process-memory only. That is acceptable for the current single-user stage, but later batch execution will need a more explicit configuration boundary.

## Next Step

Primary recommendation:
- Manually smoke-test the new cache-first and explicit-refresh flows in the browser.

Secondary recommendation:
- If refresh-path latency is still too high, add DNS preflight and fast-fail logic in market and report fetch paths.

Suggested smoke path:
- `000333` -> `Run Analysis` -> verify cached stock snapshot loads quickly
- `000333` -> `Refresh Data` -> verify explicit refresh still works
- `000333` -> `Load Financial Report` -> verify cached summary loads
- `000333` -> `Auto Read Annual Report` twice -> verify the second run reuses the stored artifact
- restart the app -> ask one report question again -> verify Q&A still works from the persisted artifact

Current design work:
- Report Q&A design written at `/Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-01-report-qa-design.md`.
- Matching cc-sdd spec scaffold added under `/Users/brenda/Projects/investment_assistant/.kiro/specs/report-qa/`.
- Implementation plan saved at `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-01-report-qa.md`.
- Version B mainflow stability spec lives under `/Users/brenda/Projects/investment_assistant/.kiro/specs/version-b-mainflow-stability/`.
- Version B implementation plan lives at `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-11-version-b-mainflow-stability.md`.
- Report Q&A now uses SQLite-backed report artifacts as the authoritative fallback; chat transcript remains frontend-only.

Current design decision:
- LLM-backed annual-report auto-read will use browser `localStorage` plus backend session-memory configuration.
- See `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-03-31-llm-autoread-config.md`.
- Cache-first reads plus SQLite-backed report artifacts were selected for Version B.
- See `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-04-11-version-b-cache-and-artifacts.md`.

Current implementation note:
- `Auto Read Annual Report` now defaults to reusing the latest stored artifact unless `force_refresh=true`.
- `Analyze Report URL` now accepts `force_refresh` and reuses a matching stored artifact when present.
- `Load Financial Report`, single-stock analysis, and watchlist analysis now default to cache-first reads and expose explicit refresh controls.
- `Auto Read Annual Report` still returns source mode and optional LLM interpretation.
- LLM enhancement requires:
  - local browser config
  - explicit `Save for this session`
  - available report text from the fetched annual report
- Report-Q&A backend/frontend state now survives backend restarts as long as the corresponding `report_artifacts` row exists.

Operational note:
- New threads should also read `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md` when the task is expected to run with minimal user interruption.

## Working Prompt For New Threads

Use this at the top of a new thread:

```text
先读取 /Users/brenda/Projects/investment_assistant/docs/handoff.md 和当前 git diff，再继续当前任务。不要从头设计。
```

## 2026-04-10 Industry Reliability Planning
- Added design and plan docs for industry/external data reliability improvements in the industry-index-source worktree.
- Planned next implementation focus: cement parser validation, thermal coal blocked/cache semantics, unified industry fallback statuses, and industry source links.
