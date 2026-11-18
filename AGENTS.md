# Repository conventions

## Repo routing
- Warn me if the paths below appear outdated.
- Reuse existing helpers and utilities before adding new helper functions.
- Before changing CLI composition, facades, or help, follow [lightweight CLI startup](docs/Development.md#lightweight-cli-startup). Check transitive parent-package imports; declarations must not load editors, prompt engines, or host business implementations. Verify with a fresh-process help test before publishing.
- For editable installation paths, follow the [checkout registration contract](docs/How-To-User-Guides.md#install-from-a-checkout). Distinguish filesystem identity from path spelling, preserve Windows UNC authorities, retain ownership/link safeguards, and include expected/actual paths in errors. Add guidance once at the CLI boundary.
- For installation failure recovery, reuse recorded publication before-images, revision-checked authority transitions, and existing runtime/resource locks. Capture state before mutation, restore authority last, and distinguish a committed activation from cleanup failure. Application callbacks own database compatibility and external effects; installer rollback must not claim to undo them.
- Check these modules first:
  - `apprc.utils`
- If a helper is broadly reusable, place it in the appropriate shared module.
- Read `BACKLOG.md` before starting, assess related issues, and fix those that belong in your pass.
- An active pass's `TODO.md` checklist belongs beside its `PLAN.md`, not in the durable backlog.

## Project rules
- Keep install wizard prompts, completion text, verification commands, and next steps current whenever CLI commands, configuration, or installation behavior changes. Verify suggested commands against the mounted CLI; AppRC owns shared wizard/help text, and the host app owns its supplied next step. Follow the developer policy in [Development](docs/Development.md#lightweight-cli-startup).
- Do not duplicate helpers or re-implement existing utilities without checking first.
- Import `apprc`-owned utility helpers through the facade: `import apprc.utils as ut`.
- Follow the shared [terminal output and color policy](docs/Development.md#terminal-output-and-color)
  for progress, status, paths, and completion messages.
- AppRC production code must use stdlib `logging`; semantic logging helpers
  live outside this repository.
- For facade `__init__.py` files, prefer clean batch re-export imports plus file-level `# ruff: noqa: F401`; do not use redundant `symbol as symbol` aliases solely to satisfy Ruff.
- Update `README.md`, docs, and changelogs when a change affects usage,
  setup, CLI behavior, public APIs, environment variables, user-visible
  workflows, or release-relevant behavior.
- Add minimal `__main__` demo code only when it improves discoverability or manual testing.
- If a test needs a lighter setup, add or reuse a dedicated test helper instead of widening production code to `Any`.
- If a boundary is truly dynamic, model that boundary explicitly; do not probe strict domain objects defensively.
- Update `BACKLOG.md` when you find a new issue that is real, actionable, and out of scope for the current change. Do not modify it when there is nothing useful to add.

## Blocking user-input policy

- When invoking `request_user_input`, never set or pass `autoResolutionMs`.
- Treat every question as blocking and wait indefinitely for my explicit response.
- Never infer, choose, submit, or continue based on a presumed answer.
- If my answer is required, do not continue until I explicitly provide it.

## Documentation
- Read and follow [Documentation rules](docs/README.md#documentation-rules) before editing documentation.
- Keep component names and document labels fixed; use inline links to exact explanations, guides, references, and examples.

## Verification
- Review the diff for duplicate helpers, naming drift, unnecessary abstractions, and regressions.
- Run the project’s relevant lint, type-check, and test commands before considering the task done.
