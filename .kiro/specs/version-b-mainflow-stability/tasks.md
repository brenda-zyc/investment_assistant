# Tasks: Version B Mainflow Stability

1. Add a `report_artifacts` table and SQLite helpers in `/Users/brenda/Projects/investment_assistant/app/db.py`.
2. Add deterministic tests for report-artifact schema creation and round-trip fetch behavior in `/Users/brenda/Projects/investment_assistant/tests/test_db.py`.
3. Refactor stock and watchlist analysis in `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py` so cached reads are the default path and refresh is explicit.
4. Extend `/Users/brenda/Projects/investment_assistant/app/api/market_api.py` to accept refresh controls without breaking existing callers.
5. Refactor financial-report summary loading in `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py` so cached reads are the default path and refresh is explicit.
6. Persist report artifacts after successful auto-read and official-URL parsing in `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`.
7. Make `/Users/brenda/Projects/investment_assistant/app/services/report_qa_service.py` load report context from persisted artifacts by `report_key`.
8. Extend `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py` with refresh and force-refresh controls.
9. Update `/Users/brenda/Projects/investment_assistant/app/templates/index.html` so default actions stay cache-first, refresh actions are explicit, and official-disclosure-only copy is visible.
10. Add focused backend and frontend regression tests for cache-first behavior, artifact reuse, artifact-backed Q&A, and refresh wiring.
11. Run targeted pytest modules first, then the stable full-suite command from `/Users/brenda/Projects/investment_assistant/TESTING.md`.
12. Record the storage/fallback decision in `/Users/brenda/Projects/investment_assistant/docs/decisions/` during implementation.
