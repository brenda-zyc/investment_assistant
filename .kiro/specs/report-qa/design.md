# Design: Report Q&A

## Scope

Implement an inline `Ask the Report` module under the Financial Reports page. The module is not global and is intentionally scoped to the active report only.

## UI

Extend `/Users/brenda/Projects/investment_assistant/app/templates/index.html` with:
- session header showing active symbol/report
- 6 to 8 starter chips
- transcript area
- text input and Ask button
- assistant answer cards with evidence and optional citations

The Q&A input is disabled until a report is successfully loaded or auto-read.

## Session Model

The frontend owns session state in memory:
- `session_key`
- `history`
- `session_summary`

`session_key` is derived from the current symbol plus active `document_url` or `detail_url`.

When `session_key` changes, the frontend clears the transcript and starts a new session.

## API

Add `POST /api/financial-report-qa` in `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`.

Request fields:
- `symbol`
- `report_key`
- `question`
- `history`
- `session_summary`
- `use_llm`

Response fields:
- `session_key`
- `mode`
- `short_answer`
- `evidence`
- `citations`
- `confidence`
- `updated_session_summary`
- `session_reset`

## Layering

- API: validation and HTTP mapping only
- Usecase: report-key validation, context assembly, response shaping
- Service: prompt construction, fallback logic, citation extraction, LLM call

## Context Rules

Allowed sources:
- current report text
- current extracted metrics
- current Three Questions output
- current LLM Reading Notes
- last six turns and session summary

Disallowed sources:
- old report transcript after report change
- other page modules such as macro or industry data

## Failure Handling

- No active report: reject request and keep frontend disabled
- LLM unavailable: return `rule_fallback`
- Out-of-scope question: return boundary answer
- Excessive history: trim to last six turns and summarize older turns

## Testing

Backend tests:
- no report loaded
- report-key mismatch
- history truncation
- llm unavailable fallback
- out-of-scope boundary answer

Frontend tests:
- chips fill input
- disabled state before report load
- transcript reset on report change
- answer rendering with evidence and citations
