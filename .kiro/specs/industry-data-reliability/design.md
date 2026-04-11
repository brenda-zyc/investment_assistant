# Design

## Modules
- `/Users/brenda/Projects/investment_assistant/app/services/industry_data_service.py`
  - source fetch, parse, and source-specific validation
- `/Users/brenda/Projects/investment_assistant/app/usecases/industry_usecase.py`
  - cache fallback decisions and payload shaping
- `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
  - Industry Cycles and External Data table rendering
- `/Users/brenda/Projects/investment_assistant/tests/test_industry_data_service.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_industry_usecase.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`

## Data Flow
1. Fetch fresh rows with diagnostics.
2. Upsert fresh rows when they pass validation.
3. Read cached rows from SQLite.
4. Filter incompatible legacy rows.
5. Emit payload rows with consistent status and provenance fields.
6. Render readable names and links in the UI.

## Failure Handling
- `blocked` for explicit access denial such as 403.
- `cached` if refresh fails but a compatible cached row exists.
- `stale` if cached row exists but exceeds freshness threshold.
- `fetch_failed` if refresh fails and no compatible cached value exists.
- `no_data` if the spec has never produced a valid point.

## Notes
- No destructive schema change.
- Keep old cache rows in SQLite but hide incompatible ones from the payload.
- Cement parser correctness is higher priority than adding new indicators.
