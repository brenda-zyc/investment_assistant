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
