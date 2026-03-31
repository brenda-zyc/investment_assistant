# LLM Auto-Read Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit auto-read mode labeling plus a DeepSeek-first LLM settings panel that persists in browser storage and backend session memory for annual-report text interpretation.

**Architecture:** Keep rule-based annual-report assessment as the primary path, then layer optional LLM interpretation on top when report text and session config are both available. Separate source-mode labeling from LLM usage state so the UI can explain both provenance and enhancement clearly.

**Tech Stack:** FastAPI, in-memory Python service state, single-page HTML/JS frontend, pytest

---

### Task 1: Decision And Spec Updates

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md`
- Modify: `/Users/brenda/Projects/investment_assistant/docs/thread_workflow.md`
- Create: `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/requirements.md`
- Create: `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/design.md`
- Create: `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/tasks.md`

- [x] Document the decision-recording rule and feature spec.

### Task 2: Failing Tests For Mode And LLM Session Behavior

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`
- Create: `/Users/brenda/Projects/investment_assistant/tests/test_llm_service.py`

- [ ] Add failing tests for `current_mode`, LLM fallback behavior, session config masking, and frontend LLM settings hooks.

### Task 3: LLM Service And Usecase Integration

**Files:**
- Create: `/Users/brenda/Projects/investment_assistant/app/services/llm_service.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`

- [ ] Add in-memory LLM session config helpers.
- [ ] Add DeepSeek-compatible test and interpretation helpers.
- [ ] Add `current_mode`, `llm_used`, and optional `llm_analysis` to the auto-read payload.

### Task 4: API Surface

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/main.py`

- [ ] Add API routes for session config save/status and connection testing.

### Task 5: Frontend Rendering And Persistence

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/templates/index.html`

- [ ] Add current-mode and LLM-status display.
- [ ] Add LLM settings panel with `localStorage` persistence.
- [ ] Add `Save for this session` and `Test Connection` flows.
- [ ] Render an `LLM Reading Notes` section when interpretation exists.

### Task 6: Verification And Handoff

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/docs/handoff.md`
- Modify: `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/tasks.md`

- [ ] Run targeted pytest verification.
- [ ] Update handoff and task checklist.
