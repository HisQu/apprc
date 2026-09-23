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
2. [2026-09-23](#2026-09-23)
   1. [P2 / E1 \[Question\] - *Add secret companion files to each dotenv layer*](#p2--e1-question---add-secret-companion-files-to-each-dotenv-layer)
3. [2026-09-04](#2026-09-04)
   1. [P3 / E1 \[Code smell\] - *Managed-file updates have no cross-process transaction*](#p3--e1-code-smell---managed-file-updates-have-no-cross-process-transaction)
   1. [P3 / E1 \[Code smell\] - *CLI and editor composition remain monolithic*](#p3--e1-code-smell---cli-and-editor-composition-remain-monolithic)
4. [2026-07-14](#2026-07-14)
   1. [P3 / E3 \[Tooling\] - *Stale bytecode recreates removed package namespaces*](#p3--e3-tooling---stale-bytecode-recreates-removed-package-namespaces)


<br>

# 2026-09-23

## P2 / E1 [Question] - *Add secret companion files to each dotenv layer*
- **Area:** `src/apprc/user_files`, `src/apprc/services/manager.py`,
  `src/apprc/services/inspection.py`
- **Observed while:** Designing local storage for fields declared with
  `secret=True`.
- **Why not fixed now:** This request records the feature for a separate pass.
  It changes resolution, setup, editing, migration, permission checks, and
  storage archives together.
- **Evidence:** `secret=True` currently redacts display values but does not
  choose a private file. Setup creates `apprc.user.env` and
  `apprc.storage.env` without secret companions. `archive_directory()` includes
  every member of a storage root.
- **Context:** Use `apprc.<layer>.secret.env`: `apprc.user.secret.env` beside
  the user dotenv and `apprc.storage.secret.env` in each initialized storage
  root. The chosen layer determines the folder; `secret=True` routes persisted
  values to its companion file. Read each companion after its regular file.
  Priority remains Python fallback, packaged defaults, user files, storage
  files, explicit dotenv files, then process environment, subject to the
  existing explicit-file override option. Setup creates empty companions for
  enabled layers and new storages without replacing existing files. Ordinary
  storage archives exclude `apprc.storage.secret.env`; ordinary configuration
  exports omit AppRC-managed secret values. A separate explicit export may
  include secrets for a deliberate backup. Restore creates an empty storage
  secret companion by default.
- **Suggested next step:** Specify migration of secret fields already saved in
  regular dotenv files, then implement routing for manager, CLI, and editor
  writes. On POSIX, require `0700` parent directories and `0600` secret files.
  On Windows, check the user directory and each storage root ACL; a relocated
  AppRC directory may not inherit a private app-data ACL. Reject unsafe
  locations or offer repair without silently changing an existing storage
  root. Establish restrictive permissions before writing temporary files for
  atomic replacement. Make `config doctor` report unsafe permissions and offer
  repair. Keep managed secret values out of logs, previews, diagnostics, and
  ordinary exports.
  Explain local storage in the GUI without promising that a user-selected
  storage root cannot be synced or backed up by other tools. Document the
  limits: no keychain or master password by default, and no protection from
  the same user, administrators, an unlocked session, or an unencrypted copied
  disk. Coordinate concurrent writes with the
  [managed-file transaction TODO](#p3--e1-code-smell---managed-file-updates-have-no-cross-process-transaction).

<br>

# 2026-09-04


## P3 / E1 [Code smell] - *Managed-file updates have no cross-process transaction*
- **Area:** `src/apprc/user_files/app_home/writes.py`, `src/apprc/user_files/env_files/updates.py`, `src/apprc/services/manager.py`
- **Observed while:** Implementing explicit resolution and shared management.
- **Why not fixed now:** This refactor establishes same-process serialization and stale dotenv-plan rejection; cross-process coordination is a separate design decision.
- **Evidence:** The shared `RLock` protects only this process. Another process can write after a revision check and before atomic replacement. Registry operations do not carry optimistic revisions.
- **Context:** Unique temporary files and cleanup now prevent thread collisions. They do not make registry, dotenv, or multi-file edits transactional across processes.
- **Suggested next step:** Choose one cross-process lock and conflict policy for all managed writes before shipping the Toga GUI. Include the [secret companion files](#p2--e1-question---add-secret-companion-files-to-each-dotenv-layer) in that policy and add CLI/GUI concurrent-writer tests on Linux and Windows.


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
