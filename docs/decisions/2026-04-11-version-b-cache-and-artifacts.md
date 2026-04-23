# Version B Cache-First And Report Artifact Decision

## Decision Time

- 2026-04-11

## Topic

- How Version B should make the current private-research main flows faster and more stable without introducing a separate job system.

## Options Considered

### Option 1: Keep request-time upstream fetch as the default path

- Stock analysis, watchlist analysis, and financial-report summary all try fresh upstream fetches first.
- Cached rows remain a failure fallback only.
- Report Q&A continues to rely on process-memory report context.

Reason not selected:
- This preserves the current latency bottleneck.
- It also blocks later batch work because parsed report context disappears on restart and cannot be reused outside the current process.

### Option 2: Cache-first reads plus SQLite-backed report artifacts

- Analyst-facing read paths return cached rows by default.
- Upstream refresh becomes explicit through `refresh` / `force_refresh` controls.
- Parsed annual-report artifacts are persisted into SQLite and can repopulate report Q&A after a restart.
- In-memory report context remains only a hot cache.

Why selected:
- Best fit for the current local single-user research-assistant stage.
- Fixes the most important usability problem first: read paths should be fast and predictable when cache exists.
- Removes the main future blocker for batch work without prematurely adding Celery, Redis, or a generic task runner.

### Option 3: Add a full async job layer immediately

- Introduce a background task system before stabilizing current request flows.
- Push refresh, parsing, and Q&A preparation into a scheduler or queue.

Reason not selected:
- Too much surface area for the current stage.
- It would slow down the main goal of Version B, which is to make existing flows fast and stable with minimal architecture expansion.

## Final Choice

- Selected option: **Option 2**

## Implementation Direction

- Stock and report-summary routes default to cache-first behavior.
- `refresh` must be passed explicitly to request new upstream data.
- `Auto Read Annual Report` defaults to reusing the latest persisted artifact for the symbol.
- `Analyze Report URL` reuses an existing persisted artifact when the same `report_key` already exists and `force_refresh` is not set.
- Parsed report artifacts are stored in SQLite `report_artifacts`.
- Report Q&A uses SQLite-backed artifact loading as the authoritative fallback when process memory is empty.

## Scope Guardrails

- Do not introduce a background task queue in Version B.
- Do not move LLM session config out of backend process memory yet.
- Do not broaden report URL support beyond official disclosure links during this stage.
- Keep frontend changes focused on explicit refresh controls and user-facing status clarity.
