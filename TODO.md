# Todo list

Treat this as the parking lot for actionable problems discovered while working but intentionally left unresolved.


<br>

> [!CAUTION]
> This is git-tracked: Never record secrets, absolute paths, credentials, private host data, or speculative security claims. Use only relative paths.


> [!IMPORTANT]
>
> ## Rules
> 1) Do not remove or change this header and TOC without very good reason.
> 1) Newest at the top.
> 1) Append a new entry only when the observation is real, actionable, not already listed, and out of scope for the current change. Do not modify `TODO.md` when there is nothing useful to add.
> 1) If an issue is new and related to another issue, reference it in the `Suggested next step`. Do not create a new entry for the same problem. Place the reference in both entries (bi-directional).
> 1) If an issue was resolved, remove it and make an entry in the CHANGELOG.md.
> 1) **Types:**
>       - **Bug risk**: Potential defect with concrete evidence, not yet confirmed.
>       - **Code smell**: Implementation, architectural, maintainability or clarity issue that is not currently a defect.
>       - **Docs drift**: Documentation is stale, incomplete, or inconsistent.
>       - **Tooling**: Issue with build, test, lint, type-check, and general slowdown of developer workflow.
>       - **Security**: Evidence-backed security risk. Use Question for uncertainty.
>       - **Question**: Design, behavior, or ownership uncertainty needing investigation.
>
> 1) **Priorities:**
>       - **P1**: Should be handled ASAP.
>       - **P2**: Should be handled before next release or milestone.
>       - **P3**: Useful cleanup for a later focused pass.
> 1) **Effort:**
>       - **E1**: Issue deserves its own focused pass.
>       - **E2**: Can be batched with a few other issues.
>       - **E3**: Can be batched with many other issues.
> 1) **Format:**
> ```markdown
>
> <br>
>
> # YYYY-MM-DD
>
> ## <Priority> / <Effort> [<Type>] - *Short problem title*
> - **Area:** `path/or/symbol`
> - **Observed while:** short context
> - **Evidence:** concrete observation
> - **Why not fixed now:** scope, risk, uncertainty, or user decision needed
> - **Suggested next step:** smallest reasonable follow-up. If applicable, reference related todos [here](#todo-list).
>
> ## <Priority> / <Effort> [<Type>] - *Short problem title*
> - **Area:** `path/or/symbol`
> - ...
>
> <br>
>
> # YYYY-MM-DD
>
> ## <Priority> / <Effort> [<Type>] - *Short problem title*
> - **Area:** `path/or/symbol`
> - ...
> ```



<br>

---

<br>

## Table Of Contents

1. [Todo list](#todo-list)
   1. [Table Of Contents](#table-of-contents)
2. [2026-07-02](#2026-07-02)
   1. [P2 / E2 [Question] - Decide whether selector-unaware config hooks should stay public](#p2--e2-question---decide-whether-selector-unaware-config-hooks-should-stay-public)
   1. [P3 / E2 [Bug risk] - Storage registration rollback hides cleanup failures](#p3--e2-bug-risk---storage-registration-rollback-hides-cleanup-failures)
   1. [P3 / E2 [Code smell] - TUI storage workflow mixins rely on runtime stubs](#p3--e2-code-smell---tui-storage-workflow-mixins-rely-on-runtime-stubs)


<br>

# 2026-07-02

## P2 / E2 [Question] - *Decide whether selector-unaware config hooks should stay public*
- **Area:** `src/apprc/definition/app_config/kit.py::AppConfigKit.typer_app`, `src/apprc/interfaces/cli/mount.py`, `src/apprc/interfaces/cli/runtime.py`, `src/apprc/interfaces/cli/config_command/_base.py`
- **Observed while:** deep TODO scan after the CLI runtime rewrite.
- **Evidence:** Public APIs still expose both `active_storage_root` / `initial_storage` and selector-aware `active_storage_root_with_context` / `initial_storage_with_context` hooks. `ConfigCommandBase.active_storage_root_for_cli()` prefers the context-aware hook but falls back to `active_storage_root`, and `tests/test_config_commands.py::test_legacy_active_storage_hook_still_works` names the older path "legacy".
- **Why not fixed now:** This is a public API decision. Removing the selector-unaware hooks is a breaking change, while keeping them probably needs clearer naming and tests instead of "legacy" wording.
- **Suggested next step:** Decide whether 0.x cleanups should keep or remove the selector-unaware hooks. If kept, rename the legacy test and document the hooks as intentionally simpler APIs. If removed, delete the fallback path, update docs, and add a breaking changelog entry.

## P3 / E2 [Bug risk] - *Storage registration rollback hides cleanup failures*
- **Area:** `src/apprc/user_files/storage_roots/registry.py::_rollback_created_storage_artifacts`
- **Observed while:** scanning for silent TODO-like behavior and broad exception suppression.
- **Evidence:** Failed `register_storage()` calls attempt to remove a newly-created empty storage env file and root directory, but both cleanup operations catch `OSError` and `pass`. Existing tests cover successful rollback and keeping an existing non-empty root, but not failed rollback cleanup.
- **Why not fixed now:** The desired behavior needs a small design choice: preserve the original write/setup exception, surface cleanup failure as a warning/log, or raise a grouped/chained error.
- **Suggested next step:** Add tests that force `storage_env.unlink()` and `root.rmdir()` to fail during rollback, then make cleanup failures observable without hiding the original registration failure.

## P3 / E2 [Code smell] - *TUI storage workflow mixins rely on runtime stubs*
- **Area:** `src/apprc/interfaces/tui/editor/storage_base.py`, `src/apprc/interfaces/tui/editor/storage_archive.py`, `src/apprc/interfaces/tui/editor/workflows.py`
- **Observed while:** scanning for `NotImplementedError` placeholders.
- **Evidence:** `StorageWorkflowBase` defines async `register_storage_directory_flow()` and `remove_live_storage()` methods that only raise `NotImplementedError`. `StorageArchiveWorkflows` calls those methods but does not implement them; the calls are valid only when the final `ConfigEditorStorageWorkflows` multiple-inheritance class combines archive, registration, and removal workflows.
- **Why not fixed now:** Current behavior is covered through the final coordinator class, and changing the workflow ownership shape deserves a focused refactor plus TUI regression tests.
- **Suggested next step:** Make the cross-workflow contract explicit. Either use an abstract base/protocol that prevents incomplete workflow instantiation, or move the cross-action orchestration into `ConfigEditorStorageWorkflows` so leaf workflow classes do not depend on runtime stubs.
