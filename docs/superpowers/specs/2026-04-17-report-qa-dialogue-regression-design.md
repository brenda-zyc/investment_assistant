# Report QA Dialogue Regression Design

## Goal

Add end-to-end dialogue regression coverage for report Q&A so future changes are checked against realistic multi-turn user behavior instead of isolated helper behavior.

The target is not more unit-style assertions. The target is stable protection for:

- multi-turn report-grounded Q&A
- hybrid LLM plus rule-fallback behavior
- follow-up anchoring across turns
- scope transitions between report-grounded answers and general LLM answers

## Current State

`tests/test_report_qa_service.py` already covers many single-behavior cases:

- cached context loading
- LLM payload normalization
- direct metric fallback
- growth-driver fallback
- profit-quality fallback
- follow-up anchoring
- scope rejection

What is still missing is conversation-level protection. Right now a future refactor could preserve all the single tests while still breaking how answers evolve across a sequence of related questions.

## Product Boundary

### In-report questions

Questions that are within the active annual-report scope continue to use the current report Q&A flow:

- `rule_fallback`
- `llm_hybrid`

These answers may use report context, extracted metrics, cached answers, citations, and report-grounded evidence.

### Out-of-report questions

When a user asks a question outside the active report scope during a report Q&A session, the system should not pretend the answer is report-grounded.

Instead it should use a distinct mode:

- `out_of_report_llm`

This mode has these rules:

- the answer is produced by general LLM behavior, not report-grounded evidence semantics
- the answer must not be framed as if it came from the active annual report
- the turn must not update the report-session follow-up anchor
- the turn must not overwrite or pollute report `session_summary`
- a later return to an in-report follow-up should still reconnect to the last valid report-scoped turn

This keeps the dialogue continuous without corrupting the report Q&A state machine.

## Recommended Test Shape

Keep the tests in `tests/test_report_qa_service.py`, but organize new coverage as dialogue scripts instead of isolated helper cases.

Each dialogue test should:

1. build one realistic report context
2. maintain a mutable `history`
3. call `answer_report_question(...)` turn by turn
4. append the assistant output back into `history`
5. assert behavior on each turn

Assertions should prefer behavior over exact prose. Tests should focus on:

- answer mode
- whether the current turn answers the current question
- whether the answer adds new information instead of repeating the previous turn
- whether `evidence` and `citations` are filtered or refreshed appropriately
- whether follow-up anchoring uses the correct earlier turn
- whether out-of-scope turns stay isolated from report-session memory

## Proposed Regression Dialogues

### 1. Rule-Only Core Dialogue

`test_report_qa_rule_only_dialogue_flow`

Purpose:

- protect the core non-LLM report dialogue path

Conversation:

1. ask for direct metrics:
   `扣非净利润和净利润分别为多少？`
2. ask for authenticity:
   `为什么你认为净利润较为真实？`
3. ask for growth drivers:
   `今年利润增长主要来自哪里？`

Assertions:

- turn 1 returns `rule_fallback`
- turn 1 surfaces both requested metrics
- turn 2 does not collapse into another direct-metric answer
- turn 2 uses cash-flow and deducted-profit reasoning
- turn 3 does not reuse the authenticity answer
- turn 3 prefers report reason lines such as `变动原因说明`

### 2. LLM-Hybrid Core Dialogue

`test_report_qa_llm_hybrid_dialogue_flow`

Purpose:

- protect the realistic mixed path where LLM answers first and the system cleans or supplements the result

Conversation:

1. ask a direct metric question with mocked LLM output containing:
   - dense table rows
   - duplicated support
   - duplicated citations
2. ask an authenticity follow-up where mocked LLM output repeats prior support
3. ask a growth-driver follow-up where mocked LLM gives no usable fresh answer, forcing fallback

Assertions:

- turn 1 returns `llm_hybrid`
- turn 1 cleans dense table rows into compact citations
- turn 1 removes duplicate support
- turn 2 still answers the new question
- turn 2 filters support already covered by history
- turn 3 does not repeat the authenticity answer
- turn 3 returns a growth-driver answer grounded in report reason lines

### 3. Follow-Up Anchoring Dialogue

`test_report_qa_follow_up_dialogue_flow`

Purpose:

- protect weak follow-up behavior across multiple turns

Conversation:

1. ask:
   `经营现金流和净利润匹配吗？`
2. ask:
   `为什么这么说？`
3. ask:
   `也没有展开呀`
4. ask one generic follow-up without a usable anchor

Assertions:

- turn 2 anchors to turn 1
- turn 3 still anchors to the most recent substantive report-scoped question
- the no-anchor follow-up returns a clarification or boundary-style response instead of fabricating an answer

### 4. Scope Boundary Dialogue

`test_report_qa_scope_boundary_dialogue_flow`

Purpose:

- protect the transition between report-scoped answers and general LLM answers

Conversation:

1. ask an in-report question:
   `净利润是否为真？`
2. ask an out-of-report question:
   `那现在估值贵不贵？`
3. ask another out-of-report question:
   `行业景气度怎么样？`
4. return to an in-report follow-up:
   `为什么你这么判断净利润？`

Assertions:

- turn 1 returns `rule_fallback` or `llm_hybrid`
- turn 2 returns `out_of_report_llm`
- turn 3 returns `out_of_report_llm`
- turns 2 and 3 do not require report evidence/citations semantics
- turns 2 and 3 do not update the report-session follow-up anchor
- turn 4 reconnects to turn 1's report context instead of anchoring to the out-of-report turns

## Test Helpers

To keep dialogue tests readable, add a very small local helper in the test file only.

Suggested shape:

`ask_and_append(history, question, *, use_llm, session_summary, symbol, report_key)`

Responsibilities:

- call `answer_report_question(...)`
- append the user turn and assistant turn back into `history`
- preserve assistant `evidence` and `citations`
- return the payload and next `session_summary`

Keep this helper test-local. Do not add production abstractions for test ergonomics.

## Non-Goals

- no immediate refactor of `app/services/report_qa_service.py`
- no migration of these tests into another file yet
- no integration with market or industry APIs for out-of-report turns
- no attempt to make out-of-report answers data-grounded at this stage

## Implementation Notes

- Write each dialogue test first and verify that it fails for the intended reason before implementation changes.
- Prefer one dialogue fixture context that already contains:
  - report text with reason lines
  - extracted metrics
  - a small cached answer set
- Mock the LLM deterministically per turn rather than building one giant generic fake.
- Do not assert full `short_answer` prose unless necessary; assert high-signal fragments and behavior.

## Acceptance Criteria

The regression test design is complete when:

- the four dialogue tests exist
- they cover both `rule_fallback` and `llm_hybrid`
- they cover `out_of_report_llm`
- they verify that out-of-report turns do not pollute report follow-up memory
- the focused report Q&A test suite passes after implementation
