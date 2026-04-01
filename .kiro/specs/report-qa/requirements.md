# Requirements: Report Q&A

## Goal

Add a report-scoped Q&A entrypoint to the Financial Reports page so the operator can ask guided follow-up questions about the currently loaded annual report.

## Requirements

1. The system shall expose a report-scoped Q&A workflow only inside the Financial Reports page.
2. The system shall anchor each Q&A session to one currently active report.
3. The system shall automatically start a new Q&A session when the active stock or active report changes.
4. The system shall keep only the most recent six turns as raw history.
5. The system shall allow older turns to be compressed into a short session summary.
6. The system shall answer only with context from the active report, current extracted metrics, current Three Questions output, current LLM Reading Notes, and bounded in-session history.
7. The system shall reject or boundary-answer questions that are outside the current report scope.
8. The system shall not output buy or sell recommendations.
9. The system shall expose a backend endpoint for one report-Q&A turn.
10. The system shall support an `llm_hybrid` answer mode when LLM is available.
11. The system shall support a `rule_fallback` answer mode when LLM is unavailable or fails.
12. The frontend shall provide guided starter questions.
13. The frontend shall disable Q&A input when no active report is loaded.
14. The response shall include a concise answer, evidence bullets, and a bounded set of citations when available.
15. The first version shall not persist report-Q&A sessions to SQLite.

## Acceptance Scenarios

### Scenario: Ask about the active report
- Given the operator has loaded a report for `000333`
- When the operator submits a report-grounded question
- Then the system returns one report-scoped answer with evidence and mode metadata

### Scenario: Switch report
- Given the operator asked questions on one report
- When the operator switches to a different stock or report
- Then the transcript resets and a new session begins automatically

### Scenario: Ask before loading report
- Given no report is loaded
- When the operator tries to ask a question
- Then the input remains disabled and the UI instructs the operator to load a report first

### Scenario: LLM unavailable
- Given the active report exists but no LLM config is available
- When the operator asks a question
- Then the system returns a conservative `rule_fallback` answer instead of failing
