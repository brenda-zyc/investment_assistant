# AGENTS.md

## Repo context

This repository is a local-first A-share investment analysis app built with:
- FastAPI backend
- SQLite persistence
- single-page HTML/JS frontend
- data-fetching services and maintenance scripts

## Default working mode

- Prefer evidence-first work: inspect the codebase and existing docs before proposing changes.
- Default to read-only analysis unless the user explicitly asks for code changes or approves a concrete fix.
- Avoid destructive commands and avoid reverting user changes unless explicitly requested.
- Keep recommendations pragmatic and scoped to the current task instead of broad refactors.

## Review guidelines

- Start review tasks with a short plan, then execute.
- Stay read-only during review unless the user explicitly asks for a fix.
- Attach file paths and line numbers to conclusions whenever possible.
- Explicitly distinguish `confirmed` findings from `suspected` risks.
- Prioritize `P0` and `P1` issues first:
  - primary-flow breakage
  - incorrect results
  - security risk
  - data-loss risk
- Do not pad reports with low-value style or formatting comments.
- Report findings in severity order.
- For high-priority findings, include when possible:
  - call chain
  - trigger condition
  - impact scope
  - minimal fix approach
  - verification method
- Call out document-versus-implementation drift explicitly when they differ.
- End review outputs with:
  - one-page summary
  - Top 5 risks
  - prioritized remediation order
  - open questions or missing context

## Source of truth

- Testing and verification commands: `TESTING.md`
- thread/process workflow: `docs/thread_workflow.md`
- project handoff and current status context: `docs/handoff.md`

## Decision log

- Important architecture, storage, security, provider, and fallback decisions should be recorded under `docs/decisions/`.
