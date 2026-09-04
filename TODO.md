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
   1. [P3 / E1 \[Bug risk\] - *Process-wide bootstrap uses per-instance locks*](#p3--e1-bug-risk---process-wide-bootstrap-uses-per-instance-locks)
   1. [P3 / E1 \[Code smell\] - *Managed-file updates have no write transaction*](#p3--e1-code-smell---managed-file-updates-have-no-write-transaction)
   1. [P3 / E1 \[Code smell\] - *Parallel declaration models obscure the supported API*](#p3--e1-code-smell---parallel-declaration-models-obscure-the-supported-api)
   1. [P3 / E1 \[Code smell\] - *Contract objects depend on persistence and interfaces*](#p3--e1-code-smell---contract-objects-depend-on-persistence-and-interfaces)
   1. [P3 / E1 \[Code smell\] - *Advanced file helpers exceed the fixed-layout contract*](#p3--e1-code-smell---advanced-file-helpers-exceed-the-fixed-layout-contract)
   1. [P3 / E1 \[Code smell\] - *CLI and editor composition remain monolithic*](#p3--e1-code-smell---cli-and-editor-composition-remain-monolithic)
   1. [P3 / E3 \[Code smell\] - *Dead legacy file resolution remains in production*](#p3--e3-code-smell---dead-legacy-file-resolution-remains-in-production)
3. [2026-07-14](#2026-07-14)
   1. [P3 / E3 \[Tooling\] - *Stale bytecode recreates removed package namespaces*](#p3--e3-tooling---stale-bytecode-recreates-removed-package-namespaces)
4. [2026-07-03](#2026-07-03)
   1. [P3 / E1 \[Code smell\] - *Config import facades look awkward*](#p3--e1-code-smell---config-import-facades-look-awkward)


<br>

# 2026-09-04

## P3 / E1 [Bug risk] - *Process-wide bootstrap uses per-instance locks*
- **Area:** `src/apprc/runtime/_bootstrap_state.py`, `src/apprc/runtime/bootstrap.py`, `src/apprc/runtime/provenance/env_registry.py`
- **Observed while:** Reviewing bootstrap state ownership and concurrency coverage.
- **Why not fixed now:** A safe fix requires choosing whether AppRC serializes all environment mutation or stops using the process environment as its intermediate state.
- **Evidence:** Each `AppRC` declaration owns a separate `RLock`, but bootstrapping mutates process-global `os.environ` and the unguarded module-global `_ENV_VALUE_ORIGINS`. Existing concurrency tests serialize calls through one declaration and do not cover two applications bootstrapping at the same time.
- **Context:** Two AppRC applications in one process can interleave environment reads, writes, and provenance registration even though each instance appears internally synchronized.
- **Suggested next step:** Introduce one process-level bootstrap transaction or compute immutable bootstrap results before a single guarded write, then add a concurrent two-application test. Preserve the existing per-declaration clean baseline while serializing process-global mutation.

## P3 / E1 [Code smell] - *Managed-file updates have no write transaction*
- **Area:** `src/apprc/user_files/app_home/locations.py`, `src/apprc/user_files/env_files/updates.py`, `src/apprc/user_files/storage_roots/_io.py`, `src/apprc/user_files/storage_roots/registry.py`
- **Observed while:** Reviewing atomic-write guarantees for the dotenv and storage registries.
- **Why not fixed now:** Cross-process locking and conflict handling need one policy shared by the CLI, TUI, bootstrap, and migration code.
- **Evidence:** `write_text_atomic()` protects only the final replacement and uses `.<name>.<pid>.tmp`, so concurrent threads in one process share a temporary path. Registry and dotenv mutations perform an unlocked read-modify-write sequence, allowing simultaneous writers to overwrite each other's changes.
- **Context:** Atomic replacement prevents a partially written destination, but it does not make a multi-step edit atomic or detect that another process changed the file after it was read.
- **Suggested next step:** Use unique same-directory temporary files plus a lock or optimistic revision check around each complete read-modify-write operation, including cleanup after failed replacement.

## P3 / E1 [Code smell] - *Parallel declaration models obscure the supported API*
- **Area:** `src/apprc/public/field.py`, `src/apprc/public/app_rc.py`, `src/apprc/definition/env_config/fields.py`, `tests/support_config.py`, `tests/test_base_config.py`
- **Observed while:** Mapping how public config declarations become runtime schema.
- **Why not fixed now:** Collapsing the models touches config derivation, compatibility helpers, and a large part of the test support layer.
- **Evidence:** `PublicFieldSpec` plus `rc.field()` duplicate most of `EnvFieldSpec` plus `env_field()`, and `AppRC._derive_internal_fields()` translates between them. The internal authoring path is not exported from the main public facade but still dominates foundational tests and support fixtures.
- **Context:** Two declaration vocabularies make it unclear which layer defines requiredness, defaults, names, and validation, while tests can pass against machinery normal users never call.
- **Suggested next step:** Move foundational fixtures to the public `AppRC` API, converge on one field schema and one derivation path, then retire the duplicate authoring helpers. Align the owner of the resulting contract with [Contract objects depend on persistence and interfaces](#p3--e1-code-smell---contract-objects-depend-on-persistence-and-interfaces).

## P3 / E1 [Code smell] - *Contract objects depend on persistence and interfaces*
- **Area:** `src/apprc/definition/app_config/spec.py`, `src/apprc/definition/app_config/kit.py`, `src/apprc/public/app_rc.py`
- **Observed while:** Checking whether the documented package layers match dependency direction.
- **Why not fixed now:** Moving these responsibilities changes internal ownership boundaries used by setup, diagnostics, the CLI, and tests.
- **Evidence:** `AppConfigSpec` imports user-file modules and provides file-creation methods, while `AppConfigKit.typer_app()` imports CLI and TUI modules. Public `AppRC.ensure_bootstrapped()` calls the kit's private `_ensure_bootstrapped()` hook and exposes both `.kit` and `.spec`, creating three overlapping facade levels.
- **Context:** A definition object should describe capabilities and validated values. File writes and interface construction make the contract depend outward on implementation layers and make it hard to identify the supported application entrypoint.
- **Suggested next step:** Keep `AppConfigSpec` as pure validated data, move setup writes and CLI construction to their owning services, and choose `AppRC` as the single application facade. Coordinate that consolidation with [Parallel declaration models obscure the supported API](#p3--e1-code-smell---parallel-declaration-models-obscure-the-supported-api).

## P3 / E1 [Code smell] - *Advanced file helpers exceed the fixed-layout contract*
- **Area:** `src/apprc/files/_facade.py`, `src/apprc/storage/_facade.py`, `src/apprc/user_files/storage_roots/_naming.py`
- **Observed while:** Comparing public helper exports with the fixed managed-filename policy.
- **Why not fixed now:** Narrowing these facades is a public API change and needs a compatibility and deprecation decision.
- **Evidence:** `apprc.files` publicly exposes arbitrary path and write primitives, while storage helpers accept custom managed filenames such as `storage_dotenv_filename`.
- **Context:** Documentation says managed filenames are fixed and there is no path-abstraction API. Public escape hatches recreate the ambiguity the 0.20 layout removed and make it unclear which paths AppRC can safely diagnose, migrate, or purge.
- **Suggested next step:** Define the supported advanced helper set and remove or deprecate filename overrides and raw managed-write exports. Remove the obsolete implementation noted in [Dead legacy file resolution remains in production](#p3--e3-code-smell---dead-legacy-file-resolution-remains-in-production) in the same compatibility pass.

## P3 / E1 [Code smell] - *CLI and editor composition remain monolithic*
- **Area:** `src/apprc/interfaces/cli/config_command/app.py`, `src/apprc/interfaces/tui/editor/app.py`
- **Observed while:** Measuring complexity after mapping interface responsibilities.
- **Why not fixed now:** The modules are heavily exercised and should be split along behavior boundaries with characterization tests, not mechanically by line count.
- **Evidence:** `build_config_typer_app_from_options()` spans roughly 335 lines and Ruff reports cyclomatic complexity 22 while it declares all nested commands and repeats storage and storage-free signatures. `ConfigEditorApp` spans 797 lines and 40 methods covering layout, input dispatch, action locking, persistence calls, selection, rendering, and control policy.
- **Context:** Existing workflow mixins extracted some storage actions, but top-level composition still centralizes enough unrelated behavior that capability rules can diverge between command variants and editor states.
- **Suggested next step:** Generate CLI variants from shared command specifications, and separate editor state/presentation from persistence orchestration. Preserve application-declared storage capability as the common policy input for both interfaces.

## P3 / E3 [Code smell] - *Dead legacy file resolution remains in production*
- **Area:** `src/apprc/user_files/managed_files.py`
- **Observed while:** Checking whether legacy path selection still participates in the 0.20 runtime.
- **Why not fixed now:** This audit intentionally records findings without changing production behavior, and the remaining `path_entry_exists()` helper still has active callers.
- **Evidence:** Repository-wide search finds no callers or tests for `ManagedFileResolution` or `resolve_managed_file()`. Their docstrings say a legacy path remains active until migration, while current runtime policy uses fixed managed paths and handles old locations only through explicit migration.
- **Context:** Dead compatibility logic beside active migration helpers can mislead future maintenance into restoring an obsolete path-selection policy.
- **Suggested next step:** Remove `ManagedFileResolution` and `resolve_managed_file()`, move `path_entry_exists()` to the migration or path utility that owns its remaining callers, and include this in the public-helper cleanup tracked by [Advanced file helpers exceed the fixed-layout contract](#p3--e1-code-smell---advanced-file-helpers-exceed-the-fixed-layout-contract).

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

# 2026-07-03

## P3 / E1 [Code smell] - *Config import facades look awkward*
- **Area:** `src/apprc/scaffold/config_package.py`, `examples/example_apps/src/*/config/_facade.py`, `examples/example_apps/src/*/config/sections/_facade.py`
- **Observed while:** Avoiding eager `config.sections` imports that can load unrelated optional section dependencies.
- **Why not fixed now:** The lazy facade plus `.pyi` approach works and passes verification, but the shape is noisy and deserves a focused design pass instead of another quick patch.
- **Evidence:** Generated config packages now need `_facade.py` modules and typed `__init__.pyi` files just to keep convenient package-level imports without eager import side effects.
- **Context:** AppRC should prevent config-layer import nonsense, but the current prevention mechanism is visually and conceptually heavy. The `_facade.py` files solve the immediate dependency leak but make the scaffold look more complicated than the config model should feel.
- **Suggested next step:** Revisit the config package import design and look for a cleaner pattern that preserves leaf-module imports, typed public surfaces, and lightweight package initialization with fewer generated support files.
