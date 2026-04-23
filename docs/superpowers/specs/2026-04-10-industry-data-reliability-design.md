# Industry Data Reliability Design

## Goal
Improve the Industry Cycles and External Data dashboards so users can trust what they see. The design focuses on three things: correct source selection, explicit fallback semantics, and readable provenance in the UI.

## Scope
This design covers only the industry/external-data reliability path in the FastAPI project:
- industry source adapters and parser validation
- cache fallback semantics for industry and external data payloads
- source links and readable labels in the UI
- source-specific freshness/status handling

Out of scope:
- adding OCR or new report-analysis features
- changing SQLite schema in a destructive way
- replacing the existing percentile logic

## Problem Summary
Recent validation showed four concrete issues:
1. `thermal_coal_index` uses `Sxcoal` as the primary source, but direct requests currently receive HTTP 403.
2. `cement_price_index` returns `ok` with a suspicious value like `1`, which is worse than a visible failure because it looks valid.
3. Industry and external-data fallback semantics are not aligned. External data clearly exposes `cached`, while industry rows reuse cached points but often present `fetch_failed` or `stale` without clearly saying the displayed value is from cache.
4. The Industry Cycles table lacks direct source links, forcing users to trust the app instead of verifying upstream pages.

## Design Principles
- Prefer honest degradation over false precision.
- A suspicious parsed value must fail validation instead of being shown as success.
- Cached fallback should be visible in the payload and the UI.
- Source-specific rules should live in service-layer adapters, not in the template.
- UI should expose human-readable labels and a direct link to the upstream page.

## Target Architecture

### 1. Source Adapter Registry
`/Users/brenda/Projects/investment_assistant/app/services/industry_data_service.py` should evolve toward an adapter-style structure for special sources.

Each source adapter should define:
- how to fetch raw content
- how to parse points
- how to validate the parsed latest point
- what source label and source URL should be exposed on success
- what fallback behavior is allowed when the source is blocked or unstable

This keeps source-specific failure handling isolated. The usecase layer should not know parser details.

### 2. Validated Success Criteria
A fetch should only be treated as `ok` when:
- the latest parsed point has a valid date
- the latest value passes source-specific sanity checks
- the source returned enough evidence to justify the parsed point

Examples:
- `cement_price_index` should reject placeholder-like values such as `1` when the parser cannot prove it came from the actual CEMPI index node.
- `thermal_coal_index` should distinguish `blocked` source access from `no_data`.

### 3. Unified Status Semantics
Both industry and external-data payloads should use a shared meaning for status values:
- `ok`: displayed value was refreshed successfully from a valid upstream source in the current run
- `cached`: displayed value comes from a compatible cached snapshot because the current refresh failed
- `stale`: displayed value comes from cache, but the cached point is older than the source-specific freshness threshold
- `blocked`: the upstream source rejected access, such as HTTP 403
- `fetch_failed`: refresh failed and there is no compatible cached value to display
- `no_data`: no valid value has ever been obtained for the current spec
- `dns_failed`: DNS preflight failed before refresh could begin

`Industry Cycles` should stop overloading `fetch_failed` to describe rows that are actually showing cached data.

### 4. Compatible Cache Filtering
The current filtering direction is correct and should remain:
- old keys like `thermal_coal` and `cement_price` may remain in SQLite
- only rows compatible with the current spec should be considered for display fallback
- incompatible legacy rows must stay hidden to avoid showing the wrong product under a corrected label

This allows safe forward migration without destructive SQL changes.

### 5. Human-Readable UI Labels
The Industry Cycles table should show:
- `display_name`
- `source`
- `Link`
- `Indicator As Of`
- `Status`
- `Note`

It should not expose raw snake_case keys to end users.

### 6. Two Timestamps, Two Meanings
The page should make the distinction explicit:
- `Indicator As Of`: the latest available date for that individual indicator
- `Refreshed At`: the time the user triggered the current refresh request

This prevents confusion when different indicators legitimately have different latest dates.

## Data Flow
1. API triggers `get_industry_cycles(...)` in `/Users/brenda/Projects/investment_assistant/app/usecases/industry_usecase.py`.
2. The usecase calls service-layer fetchers for industry data and, optionally, external data.
3. Service fetchers return rows plus diagnostics.
4. The usecase decides whether to:
   - upsert fresh rows
   - keep existing cache
   - mark rows as `cached`, `stale`, `blocked`, or `fetch_failed`
5. Payload builders return normalized rows with:
   - `indicator_key`
   - `display_name`
   - `source`
   - `source_url`
   - `status`
   - `note`
   - `as_of`
6. Frontend renders the same shape for industry rows and external rows.

## Source-Specific Strategy

### thermal_coal_index
Canonical label:
- `动力煤价格指数（CCI5500）`

Reference source:
- `Sxcoal`

Runtime strategy:
- attempt direct `Sxcoal` fetch first
- if blocked (403), mark the runtime status as `blocked`
- if a compatible cached value exists, display it as `cached` or `stale` depending on age
- if no compatible cache exists, display no value and keep the blocked error visible

This preserves the correct business definition while acknowledging source access problems.

### cement_price_index
Canonical label:
- `水泥价格指数（CEMPI）`

Reference source:
- `水泥网`

Runtime strategy:
- fetch and parse from the CEMPI page
- validate the latest parsed point against source-specific rules
- if validation fails, do not mark the row as `ok`
- prefer a visible fallback state over a suspicious success

This is the highest-priority data correctness fix because false positives are more dangerous than visible failures.

## Testing Strategy

### Service Tests
Add or extend tests in:
- `/Users/brenda/Projects/investment_assistant/tests/test_industry_data_service.py`

Cover:
- Sxcoal blocked response becomes `blocked`
- cement parser rejects suspicious placeholder values
- validated CEMPI values are accepted
- adapter metadata returns the expected label and URL

### Usecase Tests
Add or extend tests in:
- `/Users/brenda/Projects/investment_assistant/tests/test_industry_usecase.py`

Cover:
- cached compatible rows become `cached`
- stale compatible rows become `stale`
- blocked refresh with no cache becomes `blocked`
- legacy key rows remain filtered out
- payload rows expose `display_name`, `source_url`, and status/note text consistently

### Frontend Tests
Add or extend tests in:
- `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`

Cover:
- Industry table shows `display_name`
- Industry table renders `Link`
- column label is `Indicator As Of`
- cached/stale/blocked badges map to the expected text

## Maintenance Notes
This design is intentionally conservative:
- no destructive migration
- no schema rewrite
- source rules are localized to service adapters
- payload semantics are stabilized in the usecase layer

That makes it easier to add future indicators without rewriting the table or changing every consumer. The main cost is writing explicit validation rules per source, which is acceptable because correctness matters more than adapter count in this module.
