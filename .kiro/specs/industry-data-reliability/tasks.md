# Tasks

1. Tighten `cement_price_index` parsing and add validation tests for suspicious values.
2. Add explicit `blocked`/`cached`/`stale` handling for `thermal_coal_index` and compatible cache rows.
3. Normalize industry payload status semantics to match external-data behavior.
4. Add `source_url`-backed `Link` rendering to the Industry Cycles table.
5. Add `Refreshed At` display text to distinguish per-row dates from request time.
6. Run focused service/usecase/frontend tests and confirm no legacy key rows leak into the new payload.
