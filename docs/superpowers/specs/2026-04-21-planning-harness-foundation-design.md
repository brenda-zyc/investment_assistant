# Planning And Agent Harness Foundation Design

## Goal

Introduce a durable planning and handoff structure for `investment_assistant` so future work can be resumed without relying on chat history. The structure should:

- provide one structured planning source of truth
- separate planning state from agent execution rules
- make feature status and verification evidence explicit
- support incremental long-running agent workflows

## Scope

This design covers three new artifacts:

1. `docs/planning/feature_list.json`
2. `AGENT_HARNESS.md`
3. `docs/planning/progress.md`

It also defines how those artifacts relate to existing repo documents.

## Non-Goals

- Replacing existing feature specs under `.kiro/specs/`
- Replacing `docs/handoff.md` as the stage-level summary file
- Implementing product functionality changes
- Introducing a heavyweight sprint management system in v1
- Mirroring every task from `.kiro/specs/*/tasks.md` into the planning JSON

## Existing Repo Context

The repository already has useful but fragmented project memory:

- `docs/handoff.md`
  - stage summary, recent risks, recommended next step
- `.kiro/specs/*/`
  - feature-level `requirements.md`, `design.md`, and `tasks.md`
- `docs/decisions/*.md`
  - architecture, storage, provider, and fallback decisions
- `docs/superpowers/plans/*.md`
  - implementation plans
- `TESTING.md`
  - stable automated and manual verification entrypoints

The current gap is not lack of documentation. The gap is lack of a single structured planning index that tells a future agent:

- what exists
- what is complete
- what is still planned
- what has verification evidence
- what should be done next

## Reference Principles

This design follows a subset of the long-running agent harness principles described by Anthropic and the example planning repo provided by the user:

- use a structured JSON feature list as a durable planning artifact
- separate planning artifacts from agent workflow rules
- make agents work one feature at a time
- require pre-flight verification before new implementation
- separate `status` from `passes`
- keep a progress log plus git history for handoff
- avoid marking work complete without explicit verification

## Design

### 1. File Responsibilities

#### `docs/planning/feature_list.json`

This becomes the single structured planning source of truth.

It answers:

- what major work areas exist
- what executable work items exist under each area
- what state each work item is in
- what evidence exists for completion or verification
- what the next recommended action is

It does not become a dumping ground for freeform logs.

#### `AGENT_HARNESS.md`

This file defines agent work discipline only.

It should cover:

- session startup flow
- pre-flight checks
- one-feature-at-a-time rule
- when `passes` may be set to `true`
- required handoff artifacts
- how future planning requests should be phrased

It should not duplicate feature inventory or long per-feature status notes.

#### `docs/planning/progress.md`

This file records session-level handoff notes.

It should capture:

- feature id worked on
- current state of the session
- files touched
- verification performed
- blockers
- next recommended step

It complements `docs/handoff.md` instead of replacing it.

#### Existing Documents

The current repo files remain in place with narrower responsibilities:

- `docs/handoff.md`: stage-level summary
- `.kiro/specs/*/`: detailed feature specs and task breakdowns
- `docs/decisions/*.md`: important decisions
- `docs/superpowers/plans/*.md`: implementation plans
- `TESTING.md`: verification entrypoints

### 2. `feature_list.json` Top-Level Shape

The v1 file should use this top-level structure:

```json
{
  "project": "investment_assistant",
  "version": "1.0",
  "last_updated": "2026-04-21",
  "description": "Local-first A-share investment research assistant with market analysis, macro indicators, industry cycle tracking, financial report reading, and report Q&A.",
  "design_principles": [],
  "working_rules": {},
  "status_definitions": {},
  "priority_definitions": {},
  "source_documents": {},
  "epics": [],
  "features": []
}
```

Top-level fields have these roles:

- `design_principles`
  - stable project-level planning principles
- `working_rules`
  - short JSON-safe planning rules related to the feature list itself
- `status_definitions`
  - canonical meanings for `not_started`, `in_progress`, `blocked`, `completed`, and `passes`
- `priority_definitions`
  - canonical meanings for `P0` through `P3`
- `source_documents`
  - pointers to repo-level source documents
- `epics`
  - planning groups
- `features`
  - executable work items

### 3. Epic Model

The repo should group work by functional domain plus cross-cutting delivery concerns.

Initial v1 epic set:

- `DELIVERY`
- `MARKET_ANALYSIS`
- `MACRO_INDICATORS`
- `INDUSTRY_CYCLES`
- `FINANCIAL_REPORT_ANALYSIS`
- `REPORT_QA_AND_LLM`
- `RELIABILITY_AND_PERFORMANCE`
- `FRONTEND_AND_OPERATOR_EXPERIENCE`

This model is preferred over FE/BE/integration tracks because this repo is a single FastAPI plus SPA codebase, not a heavily decoupled multi-team system.

### 4. Feature Schema

Each feature entry should use a compact, explicit schema:

```json
{
  "id": "REPORT_ARTIFACTS_001",
  "epic": "FINANCIAL_REPORT_ANALYSIS",
  "title": "Persist parsed report artifacts in SQLite",
  "category": "reliability",
  "priority": "P0",
  "status": "completed",
  "passes": true,
  "user_visible": false,
  "last_updated": "2026-04-21",
  "summary": "Store parsed report text, extracted metrics, and reusable report artifacts for later reload and QA continuity.",
  "current_state": "Implemented and covered by regression tests; browser smoke verification for refresh paths is still recommended.",
  "next_action": "Run manual browser smoke checks for explicit refresh and artifact reuse flows.",
  "depends_on": [],
  "source_refs": {
    "specs": [],
    "plans": [],
    "decisions": [],
    "handoff": [],
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

Key design choices:

- `status` and `passes` are separate
- `source_refs` indexes evidence instead of copying large text
- `acceptance_checks` defines what done means
- `verification_evidence` records what was actually verified
- `current_state` and `next_action` support clean handoff

### 5. Allowed Feature Categories

The v1 schema should keep feature categories small:

- `functional`
- `reliability`
- `quality`
- `ux`
- `documentation`
- `workflow`

### 6. Initial V1 Feature Inventory

The first real planning file should include a conservative inventory of implemented, planned, and partially-verified work.

#### `DELIVERY`

- `DELIVERY_001`
  - Create structured planning source of truth
  - status: `in_progress`
  - passes: `false`
- `DELIVERY_002`
  - Add agent harness rules for planning, verification, and handoff
  - status: `not_started`
  - passes: `false`
- `DELIVERY_003`
  - Maintain session-level progress log for agent handoff
  - status: `not_started`
  - passes: `false`

#### `MARKET_ANALYSIS`

- `MARKET_001`
  - Single-symbol analysis baseline
  - status: `completed`
  - passes: `false`
- `MARKET_002`
  - Bounded concurrent watchlist fetch
  - status: `completed`
  - passes: `true`
- `MARKET_003`
  - Cache-first stock and watchlist reads with explicit refresh
  - status: `completed`
  - passes: `true`

#### `MACRO_INDICATORS`

- `MACRO_001`
  - Macro indicators dashboard baseline
  - status: `completed`
  - passes: `false`

#### `INDUSTRY_CYCLES`

- `INDUSTRY_001`
  - Industry cycles dashboard baseline
  - status: `completed`
  - passes: `false`
- `INDUSTRY_002`
  - Expose industry diagnostics with source, status, and error
  - status: `completed`
  - passes: `false`
- `INDUSTRY_003`
  - Industry data reliability cleanup
  - status: `not_started`
  - passes: `false`

#### `FINANCIAL_REPORT_ANALYSIS`

- `REPORT_001`
  - Financial report summary baseline
  - status: `completed`
  - passes: `false`
- `REPORT_002`
  - Autonomous annual-report reading
  - status: `completed`
  - passes: `true`
- `REPORT_003`
  - LLM-assisted report interpretation with session config
  - status: `completed`
  - passes: `true`
- `REPORT_004`
  - Persist report artifacts in SQLite
  - status: `completed`
  - passes: `true`
- `REPORT_005`
  - Cache-first report loading with explicit refresh controls
  - status: `completed`
  - passes: `true`
- `REPORT_006`
  - Shared report context mapping cleanup
  - status: `completed`
  - passes: `false`

#### `REPORT_QA_AND_LLM`

- `REPORT_QA_001`
  - Inline Ask-the-Report panel
  - status: `completed`
  - passes: `true`
- `REPORT_QA_002`
  - Artifact-backed report QA continuity after restart
  - status: `completed`
  - passes: `true`
- `REPORT_QA_003`
  - Dialogue regression coverage for report QA
  - status: `in_progress`
  - passes: `false`
- `REPORT_QA_004`
  - Out-of-report question routing and scope tightening
  - status: `in_progress`
  - passes: `false`

#### `RELIABILITY_AND_PERFORMANCE`

- `RELIABILITY_001`
  - SQLite contention mitigation
  - status: `completed`
  - passes: `true`
- `RELIABILITY_002`
  - Smoke verification for cache-first and refresh flows
  - status: `not_started`
  - passes: `false`
- `RELIABILITY_003`
  - Fast-fail or DNS preflight for unstable upstream sources
  - status: `not_started`
  - passes: `false`

#### `FRONTEND_AND_OPERATOR_EXPERIENCE`

- `UX_001`
  - Frontend dashboard script modularization
  - status: `completed`
  - passes: `false`
- `UX_002`
  - Refresh controls and official-disclosure-only copy clarity
  - status: `completed`
  - passes: `true`

### 7. Progress Log Format

`docs/planning/progress.md` should remain lightweight.

Recommended entry format:

```md
# Progress Log

## 2026-04-21
- Feature ID:
- Status:
- What changed:
- Files touched:
- Verification:
- Next recommended step:
- Blockers:
```

This is intentionally narrower than `docs/handoff.md`.

### 8. Future Extension Workflow

The harness should document a simple way for the user to request future planning changes in natural language.

Recommended request patterns:

- add a feature idea
- refine a feature
- split or merge features
- reprioritize features
- start implementation for a specific feature
- update status for a feature
- review the planning file for gaps or stale entries

Recommended natural-language pattern:

`Please use feature_list.json to <add / refine / split / reprioritize / implement / update / review> <feature id or topic>.`

### 9. Acceptance Criteria For This Planning Foundation

The planning foundation is complete when:

- `feature_list.json` exists in English and reflects the approved structure
- `AGENT_HARNESS.md` exists in English and defines execution discipline without duplicating the feature inventory
- `progress.md` exists in English as a session-level handoff log
- existing repo documents remain the detailed evidence layer
- initial epics and features are present with conservative `passes` values

## Risks And Mitigations

### Risk: planning drift across multiple files

Mitigation:

- keep `feature_list.json` as index and state, not a full narrative document
- use `source_refs` to point to specs, plans, decisions, tests, and code

### Risk: over-modeling the planning file

Mitigation:

- avoid FE/BE/integration tracks in v1
- avoid duplicating granular task steps that already exist in `.kiro/specs/*/tasks.md`

### Risk: agents marking work complete too early

Mitigation:

- keep `status` separate from `passes`
- require explicit verification evidence before setting `passes` to `true`

## Next Step

After user review of this design, generate:

1. `docs/planning/feature_list.json`
2. `AGENT_HARNESS.md`
3. `docs/planning/progress.md`
