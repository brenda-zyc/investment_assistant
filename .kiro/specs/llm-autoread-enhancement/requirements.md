# Requirements

## Summary

Enhance the annual-report auto-read workflow so the Financial Reports page can:

1. show the current analysis mode explicitly
2. accept DeepSeek LLM settings from the UI
3. persist those settings in both browser storage and backend session memory
4. use the configured LLM to add report-text interpretation on top of the current rule-based analysis

## Functional Requirements

### FR-1 Explicit Auto-Read Mode Label

The autonomous annual-report reader shall expose and render a stable current-mode label.

Acceptance criteria:

- The backend response shall include a field describing the current mode.
- The initial supported values shall be:
  - `historical_fallback`
  - `report_text_extracted`
- The frontend shall render the current mode in human-readable form.
- The mode shall describe the data source used for the auto-read result, not whether LLM is enabled.

### FR-2 Session-Level LLM Configuration

The backend shall support an operator-configured LLM session for report auto-read enhancement.

Acceptance criteria:

- The backend shall accept session configuration through a dedicated API route.
- The session configuration shall be stored only in process memory.
- SQLite shall not store API keys.
- The session configuration shall support:
  - provider
  - base URL
  - model
  - API key
- The backend may fall back to environment variables if no session configuration is present.

### FR-3 Browser-Level LLM Configuration Persistence

The frontend shall persist LLM settings locally for operator convenience.

Acceptance criteria:

- The Financial Reports page shall expose an LLM settings panel.
- The UI shall persist the configured provider, base URL, model, and API key in browser `localStorage`.
- The UI shall repopulate the form from `localStorage` on reload.
- The user shall explicitly push the saved browser config into backend session memory through a `Save for this session` action.

### FR-4 LLM Connectivity Validation

The system shall provide a way to validate the current LLM settings before use.

Acceptance criteria:

- The backend shall expose a dedicated test-connection route.
- The frontend shall expose a `Test Connection` action.
- The test result shall surface success or a clear failure message without crashing the page.

### FR-5 Hybrid Annual-Report Analysis

The annual-report auto-read workflow shall optionally enrich the existing rule-based output using the configured LLM.

Acceptance criteria:

- If report text is available and a valid LLM session is configured, the workflow shall request an LLM interpretation of the report text.
- The LLM shall not replace the existing deterministic three-question output.
- The response shall include explicit flags showing whether LLM enhancement was used.
- If LLM enhancement fails, the workflow shall still return the existing rule-based output with warnings.

### FR-6 Financial Reports UI Integration

The Financial Reports page shall surface the new mode and LLM-enhancement information without breaking the existing report tools.

Acceptance criteria:

- The page shall show a visible current-mode label after auto-read completes.
- The page shall show whether LLM enhancement is on, off, or unavailable.
- The page shall render a dedicated LLM interpretation section when LLM output is present.
- Existing actions `Load Financial Report` and `Analyze Report URL` shall continue to work.

## Non-Functional Requirements

### NFR-1 Security Boundary

The feature shall keep secret handling bounded and explicit.

Acceptance criteria:

- API keys shall not be written to SQLite.
- API responses shall never echo the full API key.
- Session-config inspection responses may expose only non-sensitive fields and masked key state.

### NFR-2 Graceful Degradation

The feature shall preserve partial analysis under network, parsing, or LLM failures.

Acceptance criteria:

- Auto-read shall still return rule-based answers when LLM calls fail.
- Mode labeling shall remain valid even when LLM enhancement is unavailable.
- UI rendering shall stay stable when no LLM config exists.

### NFR-3 Deterministic Testing

Core behavior shall remain testable without live LLM calls.

Acceptance criteria:

- Tests shall use monkeypatched LLM service calls.
- Tests shall cover:
  - mode selection
  - session config storage
  - LLM enhancement success
  - LLM enhancement failure fallback
