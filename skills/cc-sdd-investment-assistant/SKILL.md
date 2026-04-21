---
name: cc-sdd-investment-assistant
description: Apply a cc-sdd style spec-driven workflow to the investment_assistant FastAPI project. Use when the user wants to plan, scope, document, validate, or implement a repo change through steering files, feature specs, requirements, design notes, task breakdowns, or validation passes, or when they mention cc-sdd, Kiro-style specs, spec-init, spec-design, spec-tasks, or implementation gaps for this repository.
---

# CC SDD Investment Assistant

## Overview

Use this skill to run a local, toolchain-free version of the `cc-sdd` workflow inside this repository. Treat `.kiro/steering/` as the persistent project memory, `.kiro/specs/<feature>/` as the unit of work, and implementation as a later step that must stay aligned with the written spec.

## Workflow

1. Read the project steering docs before drafting or changing a spec:
   - `.kiro/steering/product.md`
   - `.kiro/steering/structure.md`
   - `.kiro/steering/tech.md`
2. Infer or confirm a short hyphen-case feature slug and work under `.kiro/specs/<slug>/`.
3. Write `requirements.md` first. Prefer testable "shall" statements and concrete acceptance scenarios over vague goals.
4. Write `design.md` next. Map the change to actual modules, data flow, failure handling, and tests in this repo.
5. Write `tasks.md` as small executable steps. Keep tasks implementation-oriented and easy to verify.
6. Implement only after the spec is stable or the user asks to proceed. Update docs if code reality changes.
7. Run a validation pass after implementation:
   - gap validation: does the spec still match the request?
   - design validation: does the design still match touched files?
   - implementation validation: do tests and behavior match the spec?

## Repo Constraints

- Keep API modules thin. Request validation and HTTP mapping stay in `app/api/`; orchestration belongs in `app/usecases/`; external fetch/normalization belongs in `app/services/`; persistence stays in `app/db.py`.
- Use existing TODOs and tests as anchors for meaningful specs when the user asks to "apply" the workflow without naming a feature.
- Prefer the stable test command from `TIPS.md` when verifying behavior in this environment:
  ```bash
  source .venv/bin/activate
  python3 -m pytest -p no:cov -q --override-ini addopts=''
  ```
- Keep docs concise and repo-specific. Do not paste generic agile/process filler into specs.

## Output Rules

- Cite concrete file paths in requirements, design, and tasks.
- Prefer one feature per spec directory.
- If the user only asks to "use cc-sdd here", bootstrap steering docs and one realistic spec from an existing TODO rather than inventing a large new feature.
- When details from the upstream methodology are needed, read `references/cc-sdd-workflow.md`.
