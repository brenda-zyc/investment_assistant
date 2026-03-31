# LLM Auto-Read Config Decision

## Decision Time

- 2026-03-31 14:15:36 CST

## Topic

- How the annual-report auto-read workflow should accept and store DeepSeek LLM configuration during the current project stage.

## Options Considered

### Option 1: Request-Scoped Frontend Config Only

- UI stores `api_key`, `base_url`, and `model` in browser `localStorage`.
- Every `Auto Read Annual Report` request sends the full LLM config payload to the backend.
- The backend does not keep a session-level LLM configuration.

Reason not selected:
- Fastest to build, but it duplicates config transport on every request and creates a weaker boundary for reuse across future analysis modules.

### Option 2: Browser Persistence + Backend Session Memory

- UI stores `provider`, `base_url`, `model`, and `api_key` in browser `localStorage`.
- User explicitly clicks `Save for this session` to push the config into backend process memory.
- Backend uses the in-memory session config for later auto-read requests.
- If no session config exists, backend may fall back to environment-variable configuration.

Why selected:
- Best fit for the current local single-user exploration stage.
- Preserves a clean backend calling path while still letting the operator quickly change models and providers without editing shell configuration every time.

### Option 3: Backend-Only Secret Storage

- Browser stores only non-sensitive fields such as `provider`, `base_url`, and `model`.
- `api_key` is kept only in backend process memory.
- User must re-enter the key after refresh or restart.

Reason not selected:
- Safer than Option 2, but it does not meet the current requirement to support both browser persistence and session-memory workflows.

## Final Choice

- Selected option: **Option 2**

## Implementation Direction

- Add an `LLM Settings` panel to the Financial Reports page.
- Start with DeepSeek support only.
- Provide:
  - `API Key`
  - `Base URL`
  - `Model`
  - `Save for this session`
  - `Test Connection`
- Use the saved session config only for `Auto Read Annual Report` at first.
- Keep the backend design reusable so later modules can share the same LLM session settings.

## Scope Guardrails

- Do not write API keys into SQLite.
- Do not make LLM output replace the existing rule-based analysis.
- Use LLM as an enhancement for report-text interpretation on top of the current fallback-capable rule pipeline.
