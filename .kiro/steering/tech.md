# Tech Steering

## Runtime

- Python 3.9
- FastAPI 0.118
- SQLite local persistence in `investment.db`
- AkShare as the primary upstream market/financial data dependency
- pandas and pypdf for data manipulation and report processing

## Test Strategy

- Prefer deterministic unit tests with monkeypatched provider calls.
- Avoid coupling tests to live network access.
- In this environment, use the stable pytest invocation from `TIPS.md` to bypass coverage tracer issues:

```bash
source .venv/bin/activate
python3 -m pytest -p no:cov -q --override-ini addopts=''
```

## Performance Constraints

- Upstream APIs may be slow or flaky; bounded concurrency is acceptable, unbounded fan-out is not.
- SQLite writes should stay simple and short-lived. If parallel workflows are introduced, avoid shared connections.
- Watchlist endpoints should preserve response order and graceful partial failure behavior even when parallelized.

## Operational Constraints

- Network-facing features must tolerate upstream failures and cached fallbacks.
- Keep dependencies minimal unless there is a strong payoff; prefer the standard library for concurrency and coordination.
- Do not assume coverage collection is stable on this macOS environment.
