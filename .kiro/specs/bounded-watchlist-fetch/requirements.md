# Requirements

## Summary

Improve multi-symbol watchlist analysis so it remains responsive for common watchlists without sacrificing response order, graceful partial failure handling, or the existing 20-symbol cap.

## Functional Requirements

### FR-1 Bounded Concurrent Analysis

When `analyze_multi_symbols()` receives multiple unique symbols, the system shall analyze symbols with bounded concurrency instead of strictly sequential execution.

Acceptance criteria:

- The workflow shall analyze no more than 20 symbols per request, preserving the existing cap.
- The workflow shall use a fixed upper bound on concurrent workers to avoid overloading AkShare and SQLite.
- The default worker cap shall be small enough for this environment and documented in code.

### FR-2 Stable Output Order

The system shall preserve first-seen symbol order in the `results` array even when work completes out of order.

Acceptance criteria:

- Duplicate input symbols shall still be deduplicated in first-seen order.
- Successful and failed rows shall appear in the same order as the deduplicated input list.

### FR-3 Graceful Partial Failures

If analysis for one symbol fails, the system shall return an error row for that symbol and continue processing other symbols.

Acceptance criteria:

- A `ValueError` raised during symbol normalization shall produce an error row for that raw symbol.
- A `RuntimeError` raised during per-symbol analysis shall produce an error row for that normalized symbol.
- One symbol failure shall not prevent realtime/name enrichment for other successful symbols.

### FR-4 Post-Processing Compatibility

The system shall preserve existing enrichment behavior after the concurrent analysis phase.

Acceptance criteria:

- Successful rows shall still receive stock names when available.
- Successful rows shall still receive realtime snapshots when available.
- Existing warning propagation from `analyze_single_symbol()` shall remain intact.

## Non-Functional Requirements

### NFR-1 Testability

The change shall be covered by deterministic tests that do not depend on live upstream APIs.

Acceptance criteria:

- Tests shall verify stable output order under out-of-order completion.
- Tests shall verify that duplicate symbols are deduplicated before fan-out.
- Tests shall verify that partial failures remain isolated to the affected symbol.
