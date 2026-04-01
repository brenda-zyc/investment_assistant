# Tasks: Report Q&A

1. Add a report-Q&A request/response contract in `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`.
2. Add usecase helpers in `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py` for session-key validation, bounded history handling, and report-Q&A orchestration.
3. Add service helpers in `/Users/brenda/Projects/investment_assistant/app/services/llm_service.py` or `/Users/brenda/Projects/investment_assistant/app/services/financial_report_service.py` for prompt assembly, fallback answering, and citation extraction.
4. Extend `/Users/brenda/Projects/investment_assistant/app/templates/index.html` with the inline `Ask the Report` UI, guided chips, transcript rendering, and automatic session reset on report change.
5. Add backend tests for request validation, fallback mode, report-key mismatch, and bounded history behavior.
6. Add frontend tests for disabled state, chip interaction, transcript reset, and answer rendering.
7. Run targeted pytest for the new backend and frontend tests.
