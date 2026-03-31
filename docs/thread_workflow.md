# Thread Workflow

## Purpose

Keep Codex threads short, phase-based, and easy to resume without relying on long chat history.

## Rules

1. Use one thread per stage.
- Examples:
  - feature implementation
  - bug fixing
  - refactor
  - testing
  - release preparation

2. End a thread after the stage is complete.
- Do not keep appending unrelated work to an old thread.

3. Keep project memory in repo files, not in chat history.
- Primary handoff file:
  - `/Users/brenda/Projects/investment_assistant/docs/handoff.md`
- Execution policy file:
  - `/Users/brenda/Projects/investment_assistant/docs/agent_mode.md`
- Optional long-lived files:
  - `/Users/brenda/Projects/investment_assistant/TIPS.md`
  - future `TODO.md`
  - `/Users/brenda/Projects/investment_assistant/TESTING.md`

4. Before starting a new stage, ask Codex to read the handoff file and current diff.
- Recommended opener:

```text
先读取 /Users/brenda/Projects/investment_assistant/docs/handoff.md 和当前 git diff，再继续当前任务。不要从头设计。
```

5. Keep handoff summaries concise.
- Each summary should cover:
  - current goal
  - completed work
  - in-progress changes
  - open risks
  - next step

6. Record meaningful decisions in repo docs as they are made.
- Use `/Users/brenda/Projects/investment_assistant/docs/decisions/` for important architecture, provider, storage, security, or fallback decisions.
- Do not rely on chat history as the only source of truth for those decisions.

7. Avoid pasting large raw outputs into chat.
- Prefer asking Codex to read files, logs, or diffs directly.
- Especially avoid repeatedly pasting:
  - long logs
  - full test output
  - large JSON
  - large diffs

8. If a thread becomes slow or starts automatic context compaction, migrate immediately.
- Update `docs/handoff.md`
- Open a new thread
- Continue from the handoff file

## Maintenance

- Update `/Users/brenda/Projects/investment_assistant/docs/handoff.md` whenever a stage ends.
- Treat it as the single source of truth for thread-to-thread continuity.
- Keep the file operational, not narrative.

## TODO

- Add a lightweight `TESTING.md` once manual and automated test flows stabilize.
- Add a small release checklist if local deployment becomes repeatable enough to document.
