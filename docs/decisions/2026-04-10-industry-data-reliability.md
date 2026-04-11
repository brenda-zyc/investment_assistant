# Decision: Industry Data Reliability Direction

- Date: 2026-04-10
- Context: Industry Cycles data showed a blocked thermal coal source, a suspicious cement index success value, and inconsistent fallback semantics across industry and external-data tables.

## Options Considered
1. Minimal patching only
- Fix one parser and leave current status semantics in place.

2. Reliability-first cleanup without schema migration
- Keep SQLite schema intact, but tighten parser validation, unify status semantics, and surface provenance in the UI.

3. Full storage redesign
- Introduce new persistence tables and a larger adapter framework immediately.

## Decision
Choose option 2.

## Rationale
This gives the largest trust improvement with moderate implementation cost. It avoids destructive migration while still fixing the most important problems: false-positive success rows, hidden cache fallback, and weak source provenance.
