# Agent Mode

## Goal

Allow Codex to execute a stage of work with minimal user interruption while keeping boundaries explicit and safe.

## Default Autonomous Scope

Unless the user says otherwise, Codex may do all of the following:

- read the repository state
- inspect `git diff` and relevant files
- design the change before implementation
- modify code and documentation
- run targeted tests
- run focused manual verification steps when local commands are enough
- update `/Users/brenda/Projects/investment_assistant/docs/handoff.md` at the end of a stage if the project state materially changed

## Default Non-Autonomous Scope

Codex should not assume permission to do these unless the user explicitly asks:

- destructive git actions
  - `git reset --hard`
  - history rewrite
  - force push
- dependency upgrades done only for convenience
- broad environment changes outside the project
- database deletion or cache purges
- commits, unless the current task clearly includes commit as part of the deliverable

## When Codex Must Stop And Ask

Codex should pause only for real blockers such as:

- missing credentials or network permissions
- ambiguous product choice with materially different outcomes
- unexpected user-authored changes that conflict with the current plan
- operations that need elevated permissions
- destructive actions not already approved

Codex should not stop merely to restate a plan that can be executed safely.

## Stage Execution Pattern

For each stage, Codex should:

1. read `/Users/brenda/Projects/investment_assistant/docs/handoff.md`
2. inspect the current `git diff`
3. identify the smallest relevant surface to change
4. implement directly
5. run the smallest sufficient verification
6. summarize the outcome, risks, and next step

## Expected Stage Deliverables

Each completed stage should leave behind:

- working code or a clearly explained blocker
- relevant tests or an explicit testing gap
- updated handoff content when project status changed
- a concise final summary
- recorded decision notes when the stage introduces or changes a meaningful project decision

## Decision Recording Rule

Codex shall record project decisions in repository docs instead of leaving them only in chat history.

Use this heuristic:

- Create a dedicated file under `/Users/brenda/Projects/investment_assistant/docs/decisions/` when the decision changes:
  - architecture boundaries
  - data storage behavior
  - security handling
  - external provider strategy
  - fallback semantics
  - operator workflow
- Update an existing decision file or `/Users/brenda/Projects/investment_assistant/docs/handoff.md` when the change is a minor refinement of an already-recorded decision.

Each recorded decision should include:

- decision time
- options considered
- final choice
- short reason

## Recommended New Thread Prompt

Use this when opening a fresh thread:

```text
先读取 /Users/brenda/Projects/investment_assistant/docs/handoff.md 和当前 git diff，再继续当前任务。不要从头设计。

你默认自主推进：
- 自行做设计、实现、测试、必要文档更新
- 阶段完成后更新 handoff
- 非必要不要停下来问我
- 只有 blocker、权限问题、或关键产品取舍时再问我
```

## Validation Standard

Codex should prefer:

- targeted test execution over full-suite runs when the change is local
- repo files over chat history as the source of truth
- short operational summaries over long narrative explanations

Reference:
- `/Users/brenda/Projects/investment_assistant/TESTING.md`
- `/Users/brenda/Projects/investment_assistant/TIPS.md`

## TODO

- Decide whether `.kiro/steering/` will be committed as long-term project memory.
- Decide whether stage-end commits should become the default for explicitly scoped tasks.
