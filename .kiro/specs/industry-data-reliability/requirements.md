# Requirements

## Summary
The Industry Cycles and External Data dashboards shall expose trustworthy status, provenance, and fallback behavior when upstream sources fail or return suspicious values.

## Requirements
1. The system shall reject suspicious source values rather than exposing them as successful refresh results.
2. The system shall distinguish refreshed success, cached fallback, stale cache, blocked source access, fetch failure, and no-data states.
3. The system shall expose direct source links for industry rows.
4. The system shall expose readable display names instead of raw internal keys in the industry UI.
5. The system shall keep legacy incompatible cache rows hidden after key renames.
6. The system shall preserve the existing SQLite schema for industry and external data.

## Acceptance Scenarios
- If the cement parser extracts a placeholder-like value, the row is not marked `ok`.
- If `Sxcoal` returns 403 and a compatible cache exists, the thermal coal row is displayed as cached or stale, not as a fresh success.
- If `Sxcoal` returns 403 and no compatible cache exists, the row shows a blocked/fetch failure style with no misleading value.
- The Industry Cycles table shows a human-readable indicator name and an `Open` link for each row with a source URL.
- The Industry Cycles and External Data tables both use `Indicator As Of` for the per-row date label.
