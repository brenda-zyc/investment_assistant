# Tips

## Pytest CPU spike on macOS (`syspolicyd` / `trustd`)

Symptom:
- During `pytest` runs, macOS processes `syspolicyd` and `trustd` may consume high CPU.
- Stopping pytest immediately reduces CPU usage.

Likely cause:
- `pytest-cov` / `coverage` native tracer loading and signature checks in this environment.
- This is usually not caused by test business logic itself.

Quick stable command (skip coverage plugin):

```bash
source .venv/bin/activate
python -m pytest -p no:cov -q --override-ini addopts=''
```

When to use:
- Use this command for fast functional regression checks.
- Run full coverage (`pytest`) only when you explicitly need coverage reports.

TODO:
- Rebuild local Python/venv toolchain and re-verify `pytest-cov` stability on this machine.

## Service Layer Structure

Current backend service split:
- `app/services/common.py`: shared pure utilities (type/date parsing, column matching, retry/proxy helpers).
- `app/services/financial_report_service.py`: report URL/PDF/HTML fetch and report text field extraction.
- `app/services/industry_data_service.py`: industry cycle indicator fetch, normalization, diagnostics.
- `app/services/market_data_service.py`: stock/market data fetch, symbol normalization, valuation/financial series.

Wiring:
- `app/main.py` imports service modules directly.
- `app/db.py` remains persistence-only.
- Legacy compatibility modules `app/data_service.py` and `app/industry_service.py` are removed.
