# Repository conventions

## Repo routing
- Warn me if the paths below appear outdated.
- Reuse existing helpers and utilities before adding new helper functions.
- Check these modules first:
  - `apprc.utils`
- If a helper is broadly reusable, place it in the appropriate shared module.

## Project rules
- Do not duplicate helpers or re-implement existing utilities without checking first.
- Import `apprc`-owned utility helpers through the facade: `import apprc.utils as ut`.
- Import logging helpers from `apprc.logging`, for example
  `from apprc.logging import get_logger`.
- For facade `__init__.py` files, prefer clean batch re-export imports plus file-level `# ruff: noqa: F401`; do not use redundant `symbol as symbol` aliases solely to satisfy Ruff.
- Update `README.md` if a change affects usage or setup.
- Add minimal `__main__` demo code only when it improves discoverability or manual testing.
- If a test needs a lighter setup, add or reuse a dedicated test helper instead of widening production code to `Any`.
- If a boundary is truly dynamic, model that boundary explicitly; do not probe strict domain objects defensively.

## Verification
- Review the diff for duplicate helpers, naming drift, unnecessary abstractions, and regressions.
- Run the project’s relevant lint, type-check, and test commands before considering the task done.
