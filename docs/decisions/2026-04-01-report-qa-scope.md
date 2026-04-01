# Decision: Report Q&A Scope

- Decision time: 2026-04-01 11:48:18 CST

## Options Considered

1. In-page `Ask the Report` module inside Financial Reports
2. Global floating Q&A assistant across all modules
3. Drawer or modal report assistant

## Final Choice

Choose Option 1: in-page `Ask the Report` module inside Financial Reports.

## Reason

This keeps the context boundary explicit, makes automatic session reset on report change straightforward, and avoids expanding the first version into a multi-module assistant before the report-reading path is fully mature.
