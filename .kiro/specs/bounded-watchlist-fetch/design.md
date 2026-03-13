# Design

## Context

`app/usecases/market_usecase.py` currently processes watchlist symbols sequentially in `analyze_multi_symbols()`. That keeps behavior simple, but latency scales linearly with symbol count because each symbol performs price fetch, financial fetch, SQLite cache writes, and local snapshot shaping.

The repo already separates responsibilities cleanly:

- `app/api/market_api.py` keeps the HTTP contract thin.
- `app/usecases/market_usecase.py` owns deduplication, orchestration, and response shaping.
- `app/services/market_data_service.py` owns upstream AkShare access.
- `app/db.py` owns SQLite connections and persistence.

The design must improve watchlist latency without introducing two regressions that are unacceptable for this repo:

- multiplying expensive realtime/name requests per symbol
- making SQLite lock failures common under bounded fan-out

## Goals

- Reduce watchlist latency for typical 5-20 symbol requests.
- Preserve stable output order and response shape.
- Keep partial-failure behavior intact.
- Avoid extra upstream load compared with the current implementation.

## Non-Goals

- Changing the `/api/analyze-multi` response schema.
- Introducing async I/O or new dependencies.
- Parallelizing realtime quote fetches or name lookups per symbol.

## Proposed Approach

### 1. Make watchlist bounds explicit in the usecase layer

Add module-level constants in `app/usecases/market_usecase.py`:

- `WATCHLIST_MAX_SYMBOLS = 20`
- `WATCHLIST_MAX_WORKERS = 4`

These constants replace the current implicit slice and document the operational cap directly in the orchestration layer.

### 2. Narrow the worker responsibility to price + financial analysis only

Do not submit the current `analyze_single_symbol()` function directly to the thread pool.

Instead, extract a helper in `app/usecases/market_usecase.py` dedicated to the watchlist worker path. Its responsibilities are:

- fetch historical price data
- persist price cache
- fetch financial summary
- persist financial cache
- read back cached rows
- compute `latest_price`, `latest_financial`, and `close_percentile`
- return symbol-scoped warnings

It shall not:

- fetch stock names
- fetch realtime quotes
- mutate cross-symbol state

This avoids the main regression in the current draft design: `fetch_realtime_quotes()` currently loads a full-market quote table before filtering requested symbols, so invoking it once per worker would amplify upstream cost dramatically. The watchlist path must continue to do name/realtime enrichment exactly once after all worker results are assembled.

### 3. Preserve order with indexed worker collection

`analyze_multi_symbols()` should:

1. deduplicate raw symbols in first-seen order
2. cap to `WATCHLIST_MAX_SYMBOLS`
3. normalize valid symbols and emit invalid-symbol rows immediately
4. submit only valid symbols to a `ThreadPoolExecutor`
5. store completed worker outputs in an index-addressable structure
6. flatten rows back into first-seen order

The indexing key should be the position in the deduplicated/capped input list, not completion order.

### 4. Batch stock-name and realtime enrichment once per request

After ordered worker rows are assembled, derive `successful_symbols` from rows without `error` and call:

- `_attach_stock_names()`
- `_attach_realtime_snapshots()`

exactly once each.

This preserves the current response shape while keeping the expensive enrichment calls batched at the request level. It also keeps the existing rule that failed rows do not participate in enrichment.

### 5. Use broad worker-side exception capture for symbol isolation

Inside the concurrent collection phase, any exception raised by a single worker should be converted into an error row for that symbol.

The design should not special-case only `RuntimeError`. In this codebase, worker failures can surface as request-library exceptions, parsing issues, SQLite lock errors, or existing `RuntimeError` wrappers. The watchlist usecase should isolate any symbol-scoped `Exception` into:

- `{"symbol": ..., "error": "..."}`

while keeping the overall request alive for remaining symbols.

Systemic failures outside individual workers, such as executor setup failure or final enrichment failure, should keep current explicit behavior:

- batched enrichment failures become warnings on successful rows
- request-scoped orchestration failures may still bubble out if no reasonable partial fallback exists

### 6. Add SQLite contention mitigation in persistence helpers

The current persistence layer opens short-lived SQLite connections per operation, which is compatible with bounded worker fan-out, but it needs explicit contention tolerance.

Update `app/db.py` so `get_conn()` uses:

- a non-zero SQLite connect timeout
- `PRAGMA busy_timeout`

This keeps the storage model simple while materially reducing `database is locked` errors under 2-4 concurrent writers.

This design does not require shared connections, connection pooling, or a queue-based writer thread. Those would be a larger refactor and are unnecessary unless bounded fan-out still proves noisy after timeout tuning.

## File Impact

- `app/usecases/market_usecase.py`
  - add explicit watchlist constants
  - extract a watchlist worker helper that excludes name/realtime enrichment
  - refactor `analyze_multi_symbols()` to use bounded concurrency with indexed result collection
  - preserve batch enrichment after collection

- `app/db.py`
  - add SQLite busy-timeout configuration in `get_conn()`

- `tests/test_market_usecase.py`
  - add deterministic concurrency/order/failure tests

- optionally `tests/test_db.py`
  - only if connection timeout behavior is factored into a testable helper

## Risks And Mitigations

### Realtime/name call amplification

Risk:

- submitting the current `analyze_single_symbol()` directly would trigger per-symbol realtime/name fetches and then repeat batched enrichment later

Mitigation:

- the worker helper must exclude realtime and name fetches entirely
- tests should assert batched enrichment call counts

### SQLite lock noise

Risk:

- multiple workers may write `stock_prices` and `financial_reports` concurrently

Mitigation:

- keep worker cap small
- keep current short-lived per-operation connections
- configure SQLite timeout and busy timeout

### Upstream rate limiting

Risk:

- price and financial AkShare endpoints may still rate-limit under fan-out

Mitigation:

- retain a conservative worker cap
- do not parallelize batched realtime/name enrichment
- keep failure isolation per symbol so the watchlist still returns partial results

## Test Plan

Add deterministic tests in `tests/test_market_usecase.py` covering:

- stable first-seen output order under out-of-order worker completion
- deduplication before worker submission
- invalid symbol rows staying in-order with successful rows
- one worker failure becoming one error row without aborting the request
- `_attach_stock_names()` called once with only successful symbols
- `_attach_realtime_snapshots()` called once with only successful symbols
- no per-worker realtime/name fetches in the bounded-watchlist path

Do not rely only on monkeypatching the whole `analyze_single_symbol()` function, because that would hide the main regression risk. Tests should patch the lower-level fetch/persist helpers or the new watchlist worker helper so call counts and batching behavior remain observable.
