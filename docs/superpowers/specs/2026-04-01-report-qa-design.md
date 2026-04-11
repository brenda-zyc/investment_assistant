# Report Q&A Design

## Meta

- Date: 2026-04-01 11:48:18 CST
- Status: approved design, not implemented
- Scope: add a guided multi-turn Q&A entrypoint for the current financial report only

## Goal

Add an `Ask the Report` entrypoint inside the existing Financial Reports page so the operator can ask follow-up questions about the currently loaded annual report.

The feature shall:
- stay anchored to one currently loaded report
- support short multi-turn follow-up within bounded context
- auto-reset when the active stock/report changes
- prefer evidence-backed answers over broad free-form chat
- avoid buy/sell advice

## Chosen Approach

Use an in-page Q&A module inside `/Users/brenda/Projects/investment_assistant/app/templates/index.html`, backed by one new FastAPI endpoint that remains stateless on the server.

The frontend owns the temporary chat transcript and session summary. The backend receives the active report context plus the recent transcript, builds a bounded prompt, and returns one answer with evidence and citations. The backend does not persist chat history to SQLite.

This keeps the scope narrow, matches the current single-page UI, and avoids introducing a new persistence layer for a first version.

## Alternatives Considered

### Option 1: In-page `Ask the Report` module

- Pros:
  - clearest context boundary because it is physically attached to Financial Reports
  - natural auto-reset when the active report changes
  - easiest to reuse current annual-report payloads and provenance labels
- Cons:
  - not a global assistant

### Option 2: Global floating Q&A assistant

- Pros:
  - reusable across stock, macro, and industry views later
- Cons:
  - context isolation becomes harder immediately
  - increases scope and ambiguity in the first version
  - higher risk of mixing report context with unrelated modules

### Option 3: Drawer / modal report assistant

- Pros:
  - keeps the page visually lighter
- Cons:
  - weaker multi-turn readability than an inline transcript
  - extra UI state for limited benefit in the current single-page layout

### Final Choice

Choose Option 1.

It gives the strongest report-scoped mental model with the lowest implementation risk and aligns with the current Financial Reports workflow.

## UX Design

### Placement

Add a new `Ask the Report` section below `LLM Reading Notes` in the Financial Reports panel.

### Visible Elements

- session header
  - example: `Q&A Session: 000333 / 2025年年度报告`
  - small note: `A new session starts automatically when the active report changes.`
- guided question chips
- transcript area
- input row
  - one text input
  - one `Ask` button
- answer detail area embedded in each assistant response
  - concise answer
  - evidence bullets
  - optional citations
  - mode badge

### Guided Questions

Use 6 to 8 starter chips. Initial set:
- 今年利润增长主要来自哪里？
- 管理层最担心哪些风险？
- 经营现金流和净利润匹配吗？
- 资本开支压力大吗？
- 为什么你认为净利润较为真实？
- 哪些因素会削弱利润可持续性？
- 报告里提到的主要增长引擎是什么？
- 海外业务扩张的风险在哪里？

Clicking a chip fills the input box but does not auto-send.

### Disabled State

If no report is currently loaded, disable the input and show:

`Load or auto-read an annual report before asking questions.`

### Session Reset Behavior

Automatically start a new session when any of these change:
- stock symbol
- `report.document_url`
- `report.detail_url`
- manually analyzed report URL target

On reset, clear the transcript and render one system message:

`Started a new Q&A session for the active report.`

## Session Model

### Boundaries

Each Q&A session is anchored to one active report only.

Allowed answer context:
- current report text
- current extracted metrics from `autonomous_financial_report_read(...)`
- current `Three Questions` output
- current `LLM Reading Notes`
- recent Q&A turns from the same active report

Disallowed context:
- previous stock symbol transcript
- prior report transcript after report change
- unrelated macro, industry, or watchlist data

### Retention

Keep the most recent 6 Q&A turns in raw form.

Compress older turns into one `session_summary` string on the frontend. The backend may return an updated summary after each response.

### Persistence

Do not store Q&A sessions in SQLite.

For the first version, keep report Q&A state only in frontend memory. Refreshing the page resets the Q&A session.

Reason:
- simpler privacy and maintenance boundary
- no schema changes
- enough for analyst-style in-session use

## API Design

### New Endpoint

Add one endpoint in `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`:

- `POST /api/financial-report-qa`

### Request Shape

```json
{
  "symbol": "000333",
  "report_key": "000333|http://static.cninfo.com.cn/.../1225065145.PDF",
  "question": "今年利润增长主要来自哪里？",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "session_summary": "Earlier turns focused on cash conversion and export growth.",
  "use_llm": true
}
```

### Response Shape

```json
{
  "report_key": "000333|https://static.cninfo.com.cn/.../1225065145.PDF",
  "mode": "llm_hybrid",
  "short_answer": "今年利润增长主要来自海外收入扩张、ToB 业务增长和成本效率改善。",
  "evidence": [
    "海外收入 1,959 亿元，同比增长 16%。",
    "ToB 业务收入 1,228 亿元，同比增长 17.5%。"
  ],
  "citations": [
    {
      "source": "report_text",
      "snippet": "海外收入 1,959 亿元，同比增长 16%..."
    }
  ],
  "confidence": "medium",
  "updated_session_summary": "Conversation has covered profit drivers and capital intensity.",
  "session_reset": false
}
```

### Server Responsibilities

The API layer remains thin:
- validate payload
- call a usecase
- map domain failures to HTTP errors

The usecase shall:
- validate that the active report context exists
- build bounded report-scoped context
- call the report Q&A service path
- shape the stable response

The service path shall:
- assemble prompt context
- enforce report-only scope
- call LLM when available and requested
- return rule fallback output when LLM is unavailable or fails

## Backend Data Flow

### Primary Flow

1. Frontend already holds the active auto-read payload.
2. User submits a question.
3. Frontend sends:
   - current symbol
   - current `report_key`
   - recent `history`
   - `session_summary`
   - `use_llm`
4. Backend reconstructs the active answer context from the current report payload inputs.
5. Backend answers with one concise response plus evidence.
6. Frontend appends the turn and updates the in-memory session summary.

### Answer Modes

- `llm_hybrid`
  - use current report text plus extracted metrics and current assessment outputs
- `rule_fallback`
  - return a constrained answer based only on extracted metrics and existing `Three Questions` payloads when LLM is off or fails

### Why Stateless Backend

Keeping the backend stateless avoids:
- session storage design in SQLite
- report/chat desynchronization bugs across browser tabs
- server memory growth from long-lived transcripts

## Guardrails

### Allowed Question Class

Answer only questions grounded in the active annual report, such as:
- growth drivers
- cash flow quality
- capex intensity
- management-stated risks
- segment trends
- explanation of current `Three Questions` conclusions

### Out-of-Scope Behavior

When the question is not grounded in the current report, answer with a boundary message, for example:

`This Q&A session is limited to the currently loaded annual report. Please load the relevant report or narrow the question to this report.`

### Advice Restriction

Do not output buy/sell conclusions.

### Evidence Discipline

Each answer should contain:
- one short answer
- 2 to 5 evidence bullets when evidence exists
- 0 to 3 citations with short snippets
- confidence label: `high`, `medium`, or `low`

## Module Mapping

### Frontend

Extend `/Users/brenda/Projects/investment_assistant/app/templates/index.html` to add:
- Q&A session state
- guided chips
- transcript rendering
- automatic reset when active report changes

### API

Extend `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py` with `POST /api/financial-report-qa`.

### Usecase

Add orchestration to `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`.

Suggested additions:
- active report key helper
- report Q&A request validation helper
- report-scoped question-answer workflow function

### Service

Prefer adding report-Q&A-specific helper functions under `/Users/brenda/Projects/investment_assistant/app/services/llm_service.py` if the logic is mostly prompt assembly and LLM response handling.

If prompt construction becomes too large, introduce a focused helper in `/Users/brenda/Projects/investment_assistant/app/services/financial_report_service.py` for citation extraction and context assembly.

## Failure Handling

### Report Not Loaded

- frontend disables input
- backend also rejects mismatched or empty `report_key`

### LLM Unavailable

- return `mode = rule_fallback`
- answer from extracted metrics / current assessment if possible
- clearly state reduced scope when evidence is weak

### Excessive History

- frontend truncates raw history to last 6 turns
- older context is summarized into `session_summary`

### Report Changed Mid-Session

- frontend clears transcript and starts a new session automatically
- backend returns `session_reset = true` only if it detects a `report_key` mismatch against the submitted active context

## Testing Strategy

### Backend Unit Tests

Add tests for:
- rejecting Q&A when no active report context exists
- truncating history to the last 6 turns
- report-key mismatch causing reset behavior
- rule fallback when no LLM config exists
- out-of-scope question returns boundary answer
- response includes `short_answer`, `evidence`, `confidence`, and `mode`

### Frontend Tests

Add tests for:
- chips populate the input box
- ask input is disabled before report load
- transcript resets on report change
- assistant messages render evidence and citations
- session header updates with active stock/report

### Manual Smoke Tests

Use:
- `000333`
- `600900`

Validate:
- ask 2 to 3 follow-up questions on the same report
- switch stock and confirm transcript reset
- disable or break LLM config and confirm rule fallback still answers conservatively

## Open Questions Deferred

These are intentionally deferred to implementation or later specs:
- whether report Q&A should persist in `localStorage`
- whether one answer should expose exact page numbers when available
- whether future global assistant should federate this report-Q&A module

## Recommendation

Implement this as a narrow Financial Reports enhancement only after the remaining report extraction accuracy issues are improved again.

This sequencing reduces the risk that a polished Q&A UI ends up amplifying weak extraction signals.
