# Design

## Context

The repo already supports symbol-driven annual-report auto-read through:

- `app/api/financial_report_api.py`
- `app/usecases/financial_report_usecase.py`
- `app/services/financial_report_service.py`
- `app/core_logic.py`
- `app/templates/index.html`

That workflow currently has two gaps:

1. the UI does not explicitly show whether the result came from extracted report text or historical fallback
2. the workflow cannot use an operator-provided LLM to interpret unstructured report text

## Goals

- Add a stable current-mode field and UI badge for auto-read results.
- Add DeepSeek-first LLM configuration with browser persistence and backend session memory.
- Add optional LLM text interpretation without replacing the deterministic rule-based answers.
- Preserve graceful fallback when report parsing or LLM calls fail.

## Non-Goals

- Multi-user authentication for LLM settings.
- Persisting secrets in SQLite.
- Replacing the existing report-analysis routes.
- Building a generic prompt-management system.

## Proposed Architecture

### 1. Add a dedicated LLM session service

Create a focused service module, likely `app/services/llm_service.py`, responsible for:

- storing session configuration in process memory
- masking config for safe inspection
- testing connectivity against an OpenAI-compatible chat-completions endpoint
- requesting structured report-text interpretation

The initial provider target is DeepSeek, but the request shape should stay compatible with future OpenAI-style providers through `base_url + model + api_key`.

Suggested responsibilities:

- `set_session_llm_config(...)`
- `get_session_llm_config_masked()`
- `get_effective_llm_config()`
- `test_llm_connection(...)`
- `interpret_annual_report_text(...)`

### 2. Keep mode selection independent from LLM usage

Add current-mode calculation in the auto-read usecase.

Recommended rule:

- `report_text_extracted` when extracted report metrics include at least one usable core metric from fetched report text
- `historical_fallback` otherwise

This avoids conflating:

- source mode: where the evidence came from
- LLM state: whether text interpretation was added

The response should therefore expose both:

- `current_mode`
- `llm_used`

### 3. Extend the auto-read usecase instead of replacing it

Update `autonomous_financial_report_read(symbol)` so the workflow becomes:

1. fetch symbol name
2. discover latest annual report
3. fetch report text when possible
4. extract deterministic report metrics
5. fetch historical financial context
6. compute deterministic three-question answers
7. if report text exists and LLM config is available, call the LLM interpretation helper
8. return both rule-based results and optional LLM interpretation

This preserves the current fallback-capable design and keeps orchestration inside the usecase layer.

### 4. Add thin API endpoints for LLM session management

Add a small API module, or extend the existing financial-report API surface, with routes for:

- saving the session config
- reading masked session status
- testing LLM connectivity

API remains thin:

- validate payload
- call the service
- map exceptions to HTTP errors

### 5. Add a dedicated LLM settings panel in the existing report UI

Update `app/templates/index.html` to add a new panel or subsection inside Financial Reports.

The panel should include:

- provider label or selector
- base URL field
- model field
- API key field
- `Save for this session`
- `Test Connection`

Client behavior:

- save the full config in `localStorage`
- repopulate the form on reload
- only push the config to backend memory when the user clicks `Save for this session`

### 6. Render mode and LLM interpretation distinctly

The auto-read result UI should separate three layers:

1. current mode badge
2. rule-based three-question answers
3. optional LLM interpretation block

Recommended rendering rules:

- current mode always visible after auto-read
- LLM status badge visible after auto-read
- LLM block shown only when `llm_used = true` and the backend returned interpretation content

## Response Shape Changes

Extend `GET /api/financial-report-autoread` with additional fields:

- `current_mode`
- `llm_used`
- `llm_provider`
- `llm_model`
- `llm_analysis`

Suggested `llm_analysis` shape:

```json
{
  "summary": "string",
  "question_notes": [
    {
      "question_id": "profit_authenticity",
      "summary": "string",
      "evidence": ["string"]
    }
  ]
}
```

The existing fields should remain intact.

## Failure Handling

### Auto-read without LLM config

- return rule-based results
- set `llm_used = false`
- do not fail the request

### LLM config exists but connection fails

- append a warning
- return rule-based results
- set `llm_used = false`

### Report text unavailable

- current mode becomes `historical_fallback`
- skip LLM interpretation
- return rule-based results with source-mode clarity

## File Impact

- `app/services/llm_service.py`
  - new session config and LLM call helper module
- `app/usecases/financial_report_usecase.py`
  - mode selection and optional LLM orchestration
- `app/api/financial_report_api.py`
  - session-config and test-connection routes
- `app/templates/index.html`
  - mode badge, LLM settings panel, and LLM interpretation rendering
- `tests/test_financial_report_usecase.py`
  - mode selection and LLM fallback/success behavior
- `tests/test_financial_report_frontend.py`
  - mode label and LLM settings rendering behavior
- `tests/test_llm_service.py`
  - session config and connectivity helpers

## Risks And Mitigations

- Risk: secrets leak into persistence or responses
  - Mitigation: never write keys to SQLite; mask status responses
- Risk: LLM prompt output becomes unstable
  - Mitigation: request strict JSON and test parsing with monkeypatched responses
- Risk: UI state drifts between browser storage and backend memory
  - Mitigation: make `Save for this session` explicit and show backend session status
