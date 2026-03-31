# Tasks

- [x] Add annual-report disclosure discovery helpers to `app/services/financial_report_service.py`.
- [x] Extend report-text extraction to capture deducted net profit, operating cash flow, and capex cash outflow where available.
- [x] Add normalized historical context fetch helpers in `app/services/market_data_service.py` for profit quality and capital-intensity analysis.
- [x] Add pure three-question assessment logic in `app/core_logic.py`.
- [x] Add `autonomous_financial_report_read()` to `app/usecases/financial_report_usecase.py`.
- [x] Add `GET /api/financial-report-autoread` in `app/api/financial_report_api.py`.
- [x] Update the report panel in `app/templates/index.html` to trigger and render the new autonomous report-read result.
- [x] Add deterministic tests for discovery selection, extraction, and three-question scoring.
- [x] Run focused pytest checks using the no-coverage command from `TIPS.md`.
