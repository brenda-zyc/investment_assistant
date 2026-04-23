# Planning And Agent Harness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the first durable planning foundation for `investment_assistant` by adding `docs/planning/feature_list.json`, `AGENT_HARNESS.md`, and `docs/planning/progress.md` in English.

**Architecture:** Keep planning state, execution discipline, and session handoff separate. `feature_list.json` becomes the structured planning source of truth; `AGENT_HARNESS.md` defines the agent workflow rules; `progress.md` captures short session-level handoff notes without replacing `docs/handoff.md`.

**Tech Stack:** JSON, Markdown, existing repo docs, shell validation commands

---

## File Structure

- Create: `/Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json`
  - structured planning source of truth
- Create: `/Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md`
  - agent execution rules, pre-flight checks, handoff discipline, future request patterns
- Create: `/Users/brenda/Projects/investment_assistant/docs/planning/progress.md`
  - lightweight session-level progress log
- Source only: `/Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-21-planning-harness-foundation-design.md`
  - approved design document that must be reflected in the implementation
- Source only: `/Users/brenda/Projects/investment_assistant/docs/handoff.md`
- Source only: `/Users/brenda/Projects/investment_assistant/TESTING.md`
- Source only: `/Users/brenda/Projects/investment_assistant/.kiro/specs/`
- Source only: `/Users/brenda/Projects/investment_assistant/docs/decisions/`
- Source only: `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/`

## Task 1: Create The Planning Directory And Governance Skeleton

**Files:**
- Create: `/Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json`

- [ ] **Step 1: Create the planning directory**

Run:

```bash
mkdir -p /Users/brenda/Projects/investment_assistant/docs/planning
```

Expected:

- the directory `/Users/brenda/Projects/investment_assistant/docs/planning` exists

- [ ] **Step 2: Write the governance and top-level structure for `feature_list.json`**

Write this initial content to `/Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json`:

```json
{
  "project": "investment_assistant",
  "version": "1.0",
  "last_updated": "2026-04-21",
  "description": "Local-first A-share investment research assistant with market analysis, macro indicators, industry cycle tracking, financial report reading, and report Q&A.",
  "design_principles": [
    "Use structured repo artifacts instead of chat history as the long-running source of truth.",
    "Keep planning state separate from execution rules and separate from stage summaries.",
    "Prefer conservative status reporting over optimistic completion claims.",
    "Keep status and verification evidence separate by using both status and passes.",
    "Use existing repo specs, decisions, plans, tests, and code areas as the evidence layer."
  ],
  "working_rules": {
    "planning_source_of_truth": "docs/planning/feature_list.json",
    "execution_rules_document": "AGENT_HARNESS.md",
    "session_progress_log": "docs/planning/progress.md",
    "one_feature_at_a_time": true,
    "do_not_set_passes_true_without_verification": true,
    "keep_feature_list_as_state_and_index_not_narrative_log": true
  },
  "status_definitions": {
    "not_started": "The work item is accepted into planning but implementation has not started.",
    "in_progress": "The work item is actively being implemented, refined, or validated.",
    "blocked": "The work item cannot continue until an identified dependency or decision is resolved.",
    "completed": "The planned implementation work is believed to be done, but this does not automatically imply full verification.",
    "passes": "True only when the documented acceptance checks have verification evidence."
  },
  "priority_definitions": {
    "P0": "Critical for current workflow continuity, correctness, or project control.",
    "P1": "Important product or reliability work that should follow soon after P0.",
    "P2": "Useful improvement work that is valuable but not immediately blocking.",
    "P3": "Optional or later-stage improvement work."
  },
  "source_documents": {
    "handoff": "/Users/brenda/Projects/investment_assistant/docs/handoff.md",
    "testing": "/Users/brenda/Projects/investment_assistant/TESTING.md",
    "spec_root": "/Users/brenda/Projects/investment_assistant/.kiro/specs",
    "decision_root": "/Users/brenda/Projects/investment_assistant/docs/decisions",
    "plan_root": "/Users/brenda/Projects/investment_assistant/docs/superpowers/plans"
  },
  "epics": [],
  "features": []
}
```

- [ ] **Step 3: Add the initial epic list**

Replace the empty `epics` array with this content:

```json
[
  {
    "id": "DELIVERY",
    "title": "Planning, harness, and handoff discipline",
    "priority": "P0"
  },
  {
    "id": "MARKET_ANALYSIS",
    "title": "Single-symbol and watchlist market analysis flows",
    "priority": "P0"
  },
  {
    "id": "MACRO_INDICATORS",
    "title": "Macro indicator dashboards and signals",
    "priority": "P1"
  },
  {
    "id": "INDUSTRY_CYCLES",
    "title": "Industry cycle indicators, provenance, and fallback semantics",
    "priority": "P0"
  },
  {
    "id": "FINANCIAL_REPORT_ANALYSIS",
    "title": "Financial report loading, reading, and artifact persistence",
    "priority": "P0"
  },
  {
    "id": "REPORT_QA_AND_LLM",
    "title": "Ask-the-Report dialogue behavior, scope handling, and LLM assistance",
    "priority": "P0"
  },
  {
    "id": "RELIABILITY_AND_PERFORMANCE",
    "title": "Cross-cutting resilience, cache behavior, and verification work",
    "priority": "P0"
  },
  {
    "id": "FRONTEND_AND_OPERATOR_EXPERIENCE",
    "title": "Operator-facing UX clarity and frontend maintainability",
    "priority": "P1"
  }
]
```

- [ ] **Step 4: Validate the JSON syntax**

Run:

```bash
python -m json.tool /Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json >/dev/null
```

Expected:

- command exits with status `0`
- no JSON parse error is printed

## Task 2: Populate The Initial Feature Inventory

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json`

- [ ] **Step 1: Add the shared feature object shape**

Use this structure for every feature object:

```json
{
  "id": "EXAMPLE_001",
  "epic": "DELIVERY",
  "title": "Example feature",
  "category": "workflow",
  "priority": "P0",
  "status": "not_started",
  "passes": false,
  "user_visible": false,
  "last_updated": "2026-04-21",
  "summary": "One-sentence summary.",
  "current_state": "Short current state note.",
  "next_action": "Single recommended next action.",
  "depends_on": [],
  "source_refs": {
    "specs": [],
    "plans": [],
    "decisions": [],
    "handoff": [
      "/Users/brenda/Projects/investment_assistant/docs/handoff.md"
    ],
    "code_areas": [],
    "tests": []
  },
  "acceptance_checks": [],
  "verification_evidence": {
    "automated": [],
    "manual": [],
    "notes": ""
  }
}
```

- [ ] **Step 2: Add the initial feature inventory approved in the design spec**

Populate `features` with one object per item below. Use conservative `passes` values exactly as listed.

```md
DELIVERY
- DELIVERY_001 | Create structured planning source of truth | workflow | P0 | in_progress | passes=false | user_visible=false
- DELIVERY_002 | Add agent harness rules for planning, verification, and handoff | workflow | P0 | not_started | passes=false | user_visible=false
- DELIVERY_003 | Maintain session-level progress log for agent handoff | workflow | P1 | not_started | passes=false | user_visible=false

MARKET_ANALYSIS
- MARKET_001 | Single-symbol analysis baseline | functional | P1 | completed | passes=false | user_visible=true
- MARKET_002 | Bounded concurrent watchlist fetch | reliability | P0 | completed | passes=true | user_visible=true
- MARKET_003 | Cache-first stock and watchlist reads with explicit refresh | reliability | P0 | completed | passes=true | user_visible=true

MACRO_INDICATORS
- MACRO_001 | Macro indicators dashboard baseline | functional | P1 | completed | passes=false | user_visible=true

INDUSTRY_CYCLES
- INDUSTRY_001 | Industry cycles dashboard baseline | functional | P1 | completed | passes=false | user_visible=true
- INDUSTRY_002 | Expose industry diagnostics with source, status, and error | reliability | P1 | completed | passes=false | user_visible=true
- INDUSTRY_003 | Industry data reliability cleanup | reliability | P0 | not_started | passes=false | user_visible=true

FINANCIAL_REPORT_ANALYSIS
- REPORT_001 | Financial report summary baseline | functional | P1 | completed | passes=false | user_visible=true
- REPORT_002 | Autonomous annual-report reading | functional | P0 | completed | passes=true | user_visible=true
- REPORT_003 | LLM-assisted report interpretation with session config | functional | P1 | completed | passes=true | user_visible=true
- REPORT_004 | Persist report artifacts in SQLite | reliability | P0 | completed | passes=true | user_visible=false
- REPORT_005 | Cache-first report loading with explicit refresh controls | reliability | P0 | completed | passes=true | user_visible=true
- REPORT_006 | Shared report context mapping cleanup | quality | P1 | completed | passes=false | user_visible=false

REPORT_QA_AND_LLM
- REPORT_QA_001 | Inline Ask-the-Report panel | functional | P0 | completed | passes=true | user_visible=true
- REPORT_QA_002 | Artifact-backed report QA continuity after restart | reliability | P0 | completed | passes=true | user_visible=false
- REPORT_QA_003 | Dialogue regression coverage for report QA | quality | P0 | in_progress | passes=false | user_visible=false
- REPORT_QA_004 | Out-of-report question routing and scope tightening | quality | P0 | in_progress | passes=false | user_visible=true

RELIABILITY_AND_PERFORMANCE
- RELIABILITY_001 | SQLite contention mitigation | reliability | P0 | completed | passes=true | user_visible=false
- RELIABILITY_002 | Smoke verification for cache-first and refresh flows | quality | P0 | not_started | passes=false | user_visible=false
- RELIABILITY_003 | Fast-fail or DNS preflight for unstable upstream sources | reliability | P1 | not_started | passes=false | user_visible=false

FRONTEND_AND_OPERATOR_EXPERIENCE
- UX_001 | Frontend dashboard script modularization | quality | P1 | completed | passes=false | user_visible=false
- UX_002 | Refresh controls and official-disclosure-only copy clarity | ux | P1 | completed | passes=true | user_visible=true
```

- [ ] **Step 3: Attach minimal but meaningful `source_refs` to each feature**

Use these mapping rules while filling `source_refs`:

```md
- Every feature must include `/Users/brenda/Projects/investment_assistant/docs/handoff.md` in `handoff`.
- Features tied to `.kiro/specs/version-b-mainflow-stability/` must include that spec directory and `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-11-version-b-mainflow-stability.md`.
- `INDUSTRY_003` must include `/Users/brenda/Projects/investment_assistant/.kiro/specs/industry-data-reliability/` and `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-04-10-industry-data-reliability.md`.
- `REPORT_002` must include `/Users/brenda/Projects/investment_assistant/.kiro/specs/financial-report-autoread/`.
- `REPORT_003` must include `/Users/brenda/Projects/investment_assistant/.kiro/specs/llm-autoread-enhancement/` and `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-03-31-llm-autoread-config.md`.
- `REPORT_QA_001` and `REPORT_QA_002` must include `/Users/brenda/Projects/investment_assistant/.kiro/specs/report-qa/` and `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-04-01-report-qa-scope.md`.
- `REPORT_QA_003` must include `/Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-17-report-qa-dialogue-regression-design.md` and `/Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-17-report-qa-dialogue-regression.md`.
- `REPORT_QA_004` should reuse the same report-QA plan references plus the active report-QA service code area.
- `MARKET_002` must include `/Users/brenda/Projects/investment_assistant/.kiro/specs/bounded-watchlist-fetch/`.
- `RELIABILITY_001` must include `/Users/brenda/Projects/investment_assistant/app/db.py` and `/Users/brenda/Projects/investment_assistant/tests/test_db.py`.
```

- [ ] **Step 4: Validate the completed JSON and inspect the key sections**

Run:

```bash
python -m json.tool /Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json >/dev/null
rg -n '"id"|"status"|"passes"' /Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json | sed -n '1,120p'
```

Expected:

- JSON validation exits with status `0`
- the second command shows the initial feature ids, statuses, and passes values

## Task 3: Write `AGENT_HARNESS.md`

**Files:**
- Create: `/Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md`

- [ ] **Step 1: Write the harness purpose and working model**

Start the file with content equivalent to this:

```md
# Agent Harness

## Purpose

This file defines how agents should work in `investment_assistant` once `docs/planning/feature_list.json` exists.

The harness exists to prevent planning drift, premature completion claims, and context loss across long-running sessions.

## Core Model

- `docs/planning/feature_list.json` is the structured planning source of truth.
- `docs/planning/progress.md` is the short session handoff log.
- `docs/handoff.md` remains the stage-level summary.
- Agents should work on one feature at a time unless the user explicitly asks for a broader planning-only review.
```

- [ ] **Step 2: Add pre-flight, execution, verification, and handoff rules**

Add these rule sections:

```md
## Pre-Flight

- Read `docs/planning/feature_list.json`, `docs/handoff.md`, and the current git diff before implementation work.
- Confirm the target feature id, dependencies, and current status.
- Run the smallest relevant verification step before introducing new changes when the task touches executable code.

## Execution Rules

- Planning-only requests should update planning artifacts without changing application code.
- Implementation requests should update the target feature status as the work progresses.
- Do not work on multiple unrelated features in a single execution pass unless the user explicitly requests a planning-wide cleanup.

## Verification Rules

- `status` and `passes` are separate.
- `status: completed` means the implementation work appears done.
- `passes: true` is allowed only when the documented acceptance checks have verification evidence.
- If verification is partial or missing, keep `passes: false` and say what is still unverified.

## Handoff Artifacts

- Update `docs/planning/progress.md` with the feature id, files touched, verification, and next recommended step.
- Update `docs/planning/feature_list.json` when the feature state changes.
- Update `docs/handoff.md` only when a stage-level summary genuinely changes.
```

- [ ] **Step 3: Add the future request patterns the user approved**

Add a final section like this:

```md
## How To Ask For Future Extensions

Use natural language. Examples:

- "Add a new feature idea for <topic>. Planning only."
- "Refine feature <FEATURE_ID>."
- "Split feature <FEATURE_ID> into smaller executable items."
- "Reprioritize these features based on current goals."
- "Implement <FEATURE_ID> under the harness."
- "Update status for <FEATURE_ID> based on the current code and tests."
- "Review feature_list.json for gaps, stale items, or weak verification."
```

- [ ] **Step 4: Review the harness for duplication and drift**

Run:

```bash
rg -n "feature_list.json|progress.md|passes|one feature at a time|How To Ask For Future Extensions" /Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md
```

Expected:

- the harness covers workflow discipline
- it does not duplicate the full feature inventory from `feature_list.json`

## Task 4: Write `progress.md` And Validate The Artifact Set

**Files:**
- Create: `/Users/brenda/Projects/investment_assistant/docs/planning/progress.md`
- Verify: `/Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json`
- Verify: `/Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md`

- [ ] **Step 1: Write the progress log template**

Write this file:

```md
# Progress Log

This file records short session-level handoff notes for the current planning and implementation workflow.

## Entry Template

- Date:
- Feature ID:
- Status:
- What changed:
- Files touched:
- Verification:
- Next recommended step:
- Blockers:
```

- [ ] **Step 2: Verify that all three new artifacts exist and are readable**

Run:

```bash
ls -la /Users/brenda/Projects/investment_assistant/docs/planning
ls -la /Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md
```

Expected:

- `feature_list.json` exists
- `progress.md` exists
- `AGENT_HARNESS.md` exists

- [ ] **Step 3: Run a final consistency check**

Run:

```bash
python -m json.tool /Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json >/dev/null
git diff --check
```

Expected:

- JSON remains valid
- no whitespace or patch formatting errors are reported by `git diff --check`

- [ ] **Step 4: Commit the planning foundation**

Run:

```bash
git add /Users/brenda/Projects/investment_assistant/docs/planning/feature_list.json /Users/brenda/Projects/investment_assistant/docs/planning/progress.md /Users/brenda/Projects/investment_assistant/AGENT_HARNESS.md /Users/brenda/Projects/investment_assistant/docs/superpowers/specs/2026-04-21-planning-harness-foundation-design.md /Users/brenda/Projects/investment_assistant/docs/superpowers/plans/2026-04-21-planning-harness-foundation.md
git commit -m "docs(planning): add planning foundation artifacts"
```

Expected:

- a single commit records the planning foundation files

