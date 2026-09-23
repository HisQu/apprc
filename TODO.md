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
>       - **Question**: Design, behavior, or ownership uncertainty needing investigation & maybe decision.
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
> - **Area:**  `path/or/symbol`
> - **Observed while:** short context
> - **Why not fixed now:** scope, risk, uncertainty, or user decision needed
> - **Evidence:** concrete observation
> - **Context:** explanation to ensure the problem is understood in the big-picture of the repo.
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
2. [2026-09-04](#2026-09-04)
   1. [P3 / E1 \[Code smell\] - *Multi-file updates can stop between replacements*](#p3--e1-code-smell---multi-file-updates-can-stop-between-replacements)
   1. [P3 / E1 \[Code smell\] - *CLI and editor composition remain monolithic*](#p3--e1-code-smell---cli-and-editor-composition-remain-monolithic)
3. [2026-07-14](#2026-07-14)
   1. [P3 / E3 \[Tooling\] - *Stale bytecode recreates removed package namespaces*](#p3--e3-tooling---stale-bytecode-recreates-removed-package-namespaces)


<br>

# 2026-09-04


## P3 / E1 [Code smell] - *Multi-file updates can stop between replacements*
- **Area:** `src/apprc/user_files/app_home/writes.py`, `src/apprc/user_files/env_files/updates.py`, `src/apprc/services/manager.py`
- **Observed while:** Implementing explicit resolution and shared management.
- **Why not fixed now:** Cross-process locks and revision checks now serialize managed writes, but a lock cannot make two file replacements atomic after a process crash.
- **Evidence:** Secret migration writes the private companion before removing its ordinary assignment. A crash between those writes leaves both assignments; a retry remains possible, and resolution favors the private copy within that layer.
- **Context:** The same lock covers CLI and GUI writes. A two-file migration can still be interrupted; no journal or recovery protocol exists.
- **Suggested next step:** If interrupted migrations prove common, add a small recovery journal and a crash-injection test. Preserve the current value-first ordering until then.


## P3 / E1 [Code smell] - *CLI and editor composition remain monolithic*
- **Area:** `src/apprc/interfaces/cli/config_command/app.py`, `src/apprc/interfaces/tui/editor/app.py`
- **Observed while:** Moving loading and persistence policy into shared operations.
- **Why not fixed now:** Persistence and inspection now use the manager. Further extraction would concern terminal layout and event dispatch, beyond the shared-operation refactor.
- **Evidence:** The command builder still declares nested Typer commands; the editor app still owns layout, input dispatch, table refresh, and selection presentation in one class.
- **Context:** The main policy duplication is removed. Large presentation classes remain harder to navigate than their extracted storage workflows.
- **Suggested next step:** Split terminal presentation by behavior when adding new UI actions, preserving the manager boundary. Avoid a generic command-generation framework.


<br>

# 2026-07-14

## P3 / E3 [Tooling] - *Stale bytecode recreates removed package namespaces*
- **Area:** `src/apprc/runtime_config`, `src/apprc/logging`, `tests/test_architecture_public_api.py`
- **Observed while:** Running the full test suite after the named-storage TUI pass.
- **Why not fixed now:** The stale ignored directories predate this feature and cleaning or redesigning legacy-package checks is outside the storage-editor scope.
- **Evidence:** Old `__pycache__` files leave both removed directories on the source path, so Python discovers `apprc.runtime_config` and `apprc.logging` as namespace packages and two removal assertions fail.
- **Context:** A clean source tree has no legacy Python source files, but an in-place development checkout can retain ignored bytecode after the package-layout migration.
- **Suggested next step:** Decide whether local cleanup should remove obsolete cache directories or architecture tests should explicitly distinguish namespace-only remnants from importable legacy APIs.

<br>
