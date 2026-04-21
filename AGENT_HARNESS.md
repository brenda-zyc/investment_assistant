# Agent Harness

## Purpose

This file defines how agents should work in `investment_assistant` once the planning foundation exists.

The harness exists to reduce planning drift, premature completion claims, and context loss across long-running sessions.

## Core Model

- `docs/planning/feature_list.json` is the structured planning source of truth.
- `docs/planning/progress.md` is the short session handoff log.
- `docs/handoff.md` remains the stage-level summary.
- `.kiro/specs/` remains the detailed feature-spec layer.
- `docs/decisions/` remains the decision layer.
- `docs/superpowers/plans/` remains the implementation-plan layer.

Agents should work on one feature at a time unless the user explicitly asks for a planning-wide review or cleanup.

## Pre-Flight

Before implementation work:

- Read `docs/planning/feature_list.json`.
- Read `docs/handoff.md`.
- Read the current git diff or git status.
- Confirm the target feature id, priority, dependencies, and current status.
- If the task touches executable code, run the smallest relevant verification step before adding new changes.

Before planning-only work:

- Read `docs/planning/feature_list.json`.
- Read any referenced spec, decision, or handoff files relevant to the requested topic.
- Avoid changing application code unless the user explicitly moves the task into implementation.

## Execution Rules

- Planning-only requests should update planning artifacts without changing application code.
- Implementation requests should update the target feature status as the work progresses.
- Do not work on multiple unrelated features in a single execution pass unless the user explicitly asks for a broader planning cleanup.
- Treat `feature_list.json` as the index and state map, not as a long narrative log.
- Use `source_refs` to point to evidence instead of duplicating large text from specs, plans, or handoff documents.

## Verification Rules

- `status` and `passes` are separate.
- `status: completed` means the planned implementation work appears done.
- `passes: true` is allowed only when the documented acceptance checks have verification evidence.
- If verification is partial, stale, or missing, keep `passes: false` and say what is still unverified.
- Do not claim work is complete, fixed, or passing without running a fresh verification command for that claim.

## Handoff Artifacts

At the end of a session:

- Update `docs/planning/progress.md` with the feature id, what changed, files touched, verification, next recommended step, and blockers.
- Update `docs/planning/feature_list.json` if the feature state changed.
- Update `docs/handoff.md` only when the stage-level summary genuinely changes.
- If a spec, decision, or plan became outdated because of the work, update the relevant document or record the drift clearly.

## Status Discipline

Use these meanings consistently:

- `not_started`: accepted into planning, but implementation has not started
- `in_progress`: actively being implemented, refined, or validated
- `blocked`: cannot continue until a dependency or decision is resolved
- `completed`: implementation appears done, but full verification may still be pending
- `passes: true`: acceptance checks have explicit verification evidence

## How To Ask For Future Extensions

Use natural language. Examples:

- `Add a new feature idea for <topic>. Planning only.`
- `Refine feature <FEATURE_ID>.`
- `Split feature <FEATURE_ID> into smaller executable items.`
- `Merge these overlapping features: <ID1>, <ID2>.`
- `Reprioritize these features based on current goals.`
- `Implement <FEATURE_ID> under the harness.`
- `Update status for <FEATURE_ID> based on the current code and tests.`
- `Review feature_list.json for gaps, stale items, or weak verification.`

A general pattern that always works:

`Please use feature_list.json to <add / refine / split / merge / reprioritize / implement / update / review> <feature id or topic>.`
