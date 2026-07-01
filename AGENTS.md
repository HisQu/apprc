# Repository conventions

## Repo routing
- Warn me if the paths below appear outdated.
- Reuse existing helpers and utilities before adding new helper functions.
- Check these modules first:
  - `apprc.utils`
- If a helper is broadly reusable, place it in the appropriate shared module.
- Mind the TODO.md before starting, assess if issues are related to your task and fix those that should be solved as part of your pass. 

## Project rules
- Do not duplicate helpers or re-implement existing utilities without checking first.
- Import `apprc`-owned utility helpers through the facade: `import apprc.utils as ut`.
- AppRC production code must use stdlib `logging`; semantic logging helpers
  live outside this repository.
- For facade `__init__.py` files, prefer clean batch re-export imports plus file-level `# ruff: noqa: F401`; do not use redundant `symbol as symbol` aliases solely to satisfy Ruff.
- Update `README.md`, docs, and changelogs when a change affects usage,
  setup, CLI behavior, public APIs, environment variables, user-visible
  workflows, or release-relevant behavior.
- Add minimal `__main__` demo code only when it improves discoverability or manual testing.
- If a test needs a lighter setup, add or reuse a dedicated test helper instead of widening production code to `Any`.
- If a boundary is truly dynamic, model that boundary explicitly; do not probe strict domain objects defensively.
- Update the TODO.md when you find a new issue that is real, actionable, and out of scope for the current change. Do not modify `TODO.md` when there is nothing useful to add.

## User Decisions
- Never answer questions on the user's behalf.
- Do not treat recommended options, defaults, timeouts, or auto-resolution as user approval or user preference.
- If a user decision is required, ask and wait for the user’s explicit answer.
- If work can continue without the answer, clearly label any default as an assumption, not as the user's choice.

## Verification
- Review the diff for duplicate helpers, naming drift, unnecessary abstractions, and regressions.
- Run the project’s relevant lint, type-check, and test commands before considering the task done.
