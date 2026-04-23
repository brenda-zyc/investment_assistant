# CC SDD Workflow Notes

This skill adapts the ideas from `gotalab/cc-sdd` to a local Codex skill plus repo files because this machine does not currently have the Node-based installer available.

## Upstream Concepts To Mirror

- Persistent steering docs that explain the product, architecture, and technical rules.
- A feature-spec workflow that moves in this order: init -> requirements -> design -> tasks -> implementation -> validation.
- Small command prompts that let the agent enter each phase without re-explaining the whole methodology.

## Local Mapping

- Upstream `steering` output maps to `.kiro/steering/*.md`.
- Upstream feature specs map to `.kiro/specs/<feature>/requirements.md`, `design.md`, and `tasks.md`.
- Upstream Codex commands map to `.codex/prompts/kiro-*.md`.

## Repo-Specific Guidance

- Use existing module boundaries instead of redesigning the whole app:
  - `app/api/`: HTTP adapters only
  - `app/usecases/`: orchestration and workflow logic
  - `app/services/`: upstream fetch and normalization
  - `app/db.py`: SQLite persistence
- Prefer specs that target current friction points already visible in the codebase:
  - `app/usecases/market_usecase.py`: bounded parallel fetch TODO
  - `app/main.py`: environment-driven FastAPI settings TODO
  - `app/usecases/industry_usecase.py`: diagnostics endpoint TODO
- Write acceptance criteria that can be tested with deterministic unit tests before relying on live AkShare calls.

## Default Validation Loop

1. Read steering docs.
2. Read the target spec directory.
3. Check whether code changes match the task list.
4. Run focused tests first, then the broader no-coverage pytest command from `TIPS.md` when appropriate.
5. Update the spec if implementation reality changed for a justified reason.
