# Tasks

- [ ] Add explicit watchlist limit and worker-cap constants to `app/usecases/market_usecase.py`.
- [ ] Extract a watchlist-specific worker helper in `app/usecases/market_usecase.py` that fetches and caches price/financial data but does not fetch stock names or realtime quotes.
- [ ] Refactor `analyze_multi_symbols()` so valid symbols run through bounded concurrent execution while preserving first-seen order.
- [ ] Keep invalid-symbol and worker-failure rows compatible with the current response schema by converting symbol-scoped exceptions into error rows.
- [ ] Preserve single-pass `_attach_stock_names()` and `_attach_realtime_snapshots()` enrichment after concurrent collection.
- [ ] Add SQLite contention mitigation in `app/db.py` with connection timeout and busy-timeout settings.
- [ ] Add deterministic tests covering order preservation, deduplication, isolated partial failures, and one-time batch enrichment call counts.
- [ ] Run focused pytest checks with the no-coverage command from `TIPS.md`.
