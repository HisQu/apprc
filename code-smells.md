# 🔎 AppRC Code Smell Cleanup

**Goal**

Identify defects and cleanup opportunities that make AppRC easier to maintain and operate.

**Specifics**

Reviewed `main` at `11927a` (tree `3a0c57`) on Linux with Python 3.14.2. The review covered the SDK, CLI, Textual and Gradio interfaces, workspace and installation operations, packaging, workflows, docs, examples, and relevant tests. The user selected deeper edge cases and asked to consider breaking proposals. All findings are open and linked from the [backlog](BACKLOG.md#2026-11-21).

Start with the workspace move findings. A failed cross-filesystem move can delete a directory AppRC never published, and a queued move can act on a workspace root that differs from the one it locked. The secret migration snapshot has a separate stale-write risk. These findings follow from source inspection. The existing Linux tests pass and do not exercise these particular interleavings. [CSC-11](#csc-11) · [CSC-12](#csc-12) · [CSC-13](#csc-13)

## Obvious bugs

The baseline and example smoke checks exercised ordinary configuration, workspace selection, scaffold, CLI help and diagnostics, and fixture-backed installation and recovery. They exposed no primary success-path failure. The findings below identify concrete behavior in failure paths, plus maintainability and documentation improvements.

## Code smells

<a id="csc-01"></a>

### CSC-01 · P2 · Make managed and editable activation easier to trace

**Evidence and impact.** The 2,704-line runtime installer prepares runtime candidates, captures publication before-images, restores resources, publishes commands, commits installation authority, and handles post-commit Windows integration. Managed and editable paths each implement the latter sequence, including publication, checkpoints, commit, and finalization. Following a change to one of those steps requires checking both paths and the shared recovery function. The existing split between preparation and activation is a useful starting point. [Managed activation](src/apprc/distribution/runtime/installation.py#L1270) · [Candidate preparation](src/apprc/distribution/runtime/installation.py#L1559) · [Editable activation](src/apprc/distribution/runtime/installation.py#L2412)

**Correction and verification.** Give the shared publication and activation sequence a focused internal owner. Keep managed and editable preparation explicit because their inputs and recovery rules differ. Preserve lock order, before-images, checkpoint values, command ownership, and activation ordering. Use the existing managed and editable rollback and post-commit tests to establish equivalence. The refactor fits the current public API and record schema. [Rollback tests](tests/test_installation_rollback.py)

## Intuitive code traversal

<a id="csc-02"></a>

### CSC-02 · P2 · Give CLI command classification one internal entry point

**Evidence and impact.** `CliRuntime.prepare` handles the distribution route directly, then consults separate installation, diagnostic, and runtime-skip predicates. The predicates repeatedly get the current arguments, identify the nested command, and parse leading options. Some routes depend on callback identity, which distinguishes generated commands from a host command with the same name. Adding a route requires tracing several predicates to determine whether it gets installation metadata, diagnostic context, or full application state. [Preparation](src/apprc/interfaces/cli/runtime.py#L450) · [Runtime skip](src/apprc/interfaces/cli/runtime.py#L713) · [Installation and diagnostics](src/apprc/interfaces/cli/runtime.py#L777)

**Correction and verification.** Parse the invocation once where the command shape allows it and use the existing parser to select the preparation path. Keep callback identity checks, the public `CliRuntimePolicy` behavior, custom group names, option separators, and fresh-process help imports covered throughout. This is an internal refactor. Compare runtime and help tests, including host command collisions. [Runtime tests](tests/test_cli_runtime.py) · [Fresh-process distribution help](tests/test_cli_distribution.py#L107)

<a id="csc-03"></a>

### CSC-03 · P3 · Group dependency configuration tests by contract

**Evidence and impact.** The 1,613-line dependency import test module keeps collision and validation cases alongside resolution precedence, workspace requirements, runtime lifecycle, and bundle construction. The later collision tests and earlier resolution cases use different fixture shapes, but a reader has to find them in one file. [Shared fixture setup](tests/public/test_dependency_config_import.py#L23) · [Resolution cases](tests/public/test_dependency_config_import.py#L988) · [Registration rollback cases](tests/public/test_dependency_config_import.py#L1351)

**Correction and verification.** Group cases by declaration and registration, resolution, and lifecycle. Keep the fixture for each contract near the cases or reuse the existing test support area when it has multiple genuine users. Preserve the tests that establish different contracts, including failed registration and retry. This changes test placement only. Compare collected cases and run the public API suite after moving them.

## Code efficiency

<a id="csc-04"></a>

### CSC-04 · P2 · Capture a workspace target once for a grouped settings edit

**Evidence and impact.** Each field in `plan_updates` resolves its declaration and calls `plan_update`. Each secret also repeats private-file checks. Resolving a workspace write path invokes full configuration inspection, so a single grouped write may reload and inspect the same workspace several times. An implicit selection can also change while the batch is being planned because each field selects its own target. [Workspace write path](src/apprc/services/manager.py#L177) · [Single and grouped planning](src/apprc/services/manager.py#L296) · [Secret check](src/apprc/services/manager.py#L441)

**Correction and verification.** Capture the selected workspace and writable paths per operation, then reuse them for field validation and revision-checked writes. Keep private and ordinary destinations separate. Add coverage for changing an implicit workspace selection during planning and compare inspection call counts for a mixed batch. Existing grouped-write tests cover rollback. The expected benefit is fewer inspections and a single target per batch. The size of the runtime improvement is unmeasured. [Batch tests](tests/test_config_batch_updates.py)

<a id="csc-05"></a>

### CSC-05 · P3 · Bound source snapshot memory

**Evidence and impact.** The source-build path captures the whole Git tar in memory before writing it to the private stage. It later retains each input file's bytes, the ZIP buffer, and the completed ZIP bytes. The full input and archive sizes contribute to peak memory, especially for projects with large prepared assets. Native product assembly also uses the deterministic ZIP helper, so changing its contract for all callers would widen the work. [Project staging](src/apprc/distribution/project.py#L379) · [Snapshot assembly](src/apprc/distribution/project.py#L428) · [ZIP helper](src/apprc/distribution/_archives.py#L10)

**Correction and verification.** Stream Git's archive into the private stage, then evaluate writing snapshot ZIP entries to a file and hashing the result with `apprc.utils.sha256_file`. Retain the snapshot format, ordering, timestamps, file modes, digest checks, output ownership, and failure cleanup. Measure peak memory with a representative larger snapshot and verify byte-for-byte reproducibility before changing the shared ZIP implementation. [Snapshot tests](tests/test_project_snapshot.py)

The existing slot-name cache uses immutable results keyed by class and consumes one entry per class for the process lifetime. Fixed app declarations bound that cardinality in typical use. Dynamic class churn would justify measuring retention before replacing the cache. Caching mutable files or installation authority would require invalidation across processes. Repository pytest already runs independent tests in parallel. The installation and recovery steps reviewed here depend on ordered writes, and the scan found no comparable low-effort runtime parallelism opportunity. [Slot-name cache](src/apprc/runtime/config/_state_transfer.py#L32) · [Pytest options](pyproject.toml#L179)

## Documentation

<a id="csc-06"></a>

### CSC-06 · P3 · Describe the current hosted CI profiles

**Evidence and impact.** Development describes core CI on Python 3.12, 3.13, and 3.14 and GUI CI on Python 3.12 without stating when those jobs run. Regular pushes and PRs default to core Python 3.12. Eligible release tags enable the extended core matrix and GUI Python 3.14. Beta tags may skip the core jobs under the current release policy. Readers can infer coverage from a regular green run that the workflow never scheduled. [Development environment](docs/Development.md#environment) · [CI profile](.github/workflows/ci.yml#L34) · [GUI job](.github/workflows/ci.yml#L119)

**Correction and verification.** Update the environment section with the ordinary, extended-release, and beta profiles. Compare each claim with the workflow and retain the existing Windows/macOS coverage note. Documentation tests check links and examples. Profile statements require a source comparison. This is a docs-only correction.

## Error handling

<a id="csc-07"></a>

### CSC-07 · P2 · Distinguish editable sync from completed registration

**Evidence and impact.** An editable update can advance Git and synchronize dependencies before registration fails. The failure prints a direct registration retry, but the next `app update` considers equal Git tips and a successful `uv sync --check` sufficient to report the checkout and environment up to date. This can leave registration incomplete after a retry of the update. The sync-failure path also prints only the sync command, even though registration has yet to run. [Up-to-date decision](src/apprc/distribution/runtime/update.py#L236) · [Sync and registration errors](src/apprc/distribution/runtime/_update_handoff.py#L150) · [Documented retry](docs/How-To-User-Guides.md#update-an-application)

**Correction and verification.** Give a direct recovery command for each unfinished step and make a repeat update recognize outstanding registration work before declaring the operation complete. First assess whether existing installation evidence can establish completion. Add a fixture that fails registration after sync and then retries. The existing partial-failure test covers sync failure. Keep the CLI shape and record schema unless a separate design establishes a need to change them. [Editable update test](tests/test_distribution_update.py#L181)

## UX and messages

<a id="csc-08"></a>

### CSC-08 · P2 · Show workspace move cleanup warnings in the CLI

**Evidence and impact.** A completed move can keep the old root because the source changed or could not be cleaned up. The move returns warnings explaining what remains. Textual displays them, while the mounted `workspace move` command discards the result. A terminal user receives neither that context nor the resulting root. [Move result](src/apprc/user_files/workspace_roots/move.py#L241) · [CLI handler](src/apprc/interfaces/cli/maintenance_command.py#L739) · [Textual handler](src/apprc/interfaces/tui/editor/workspace_editing.py#L220)

**Correction and verification.** Use the shared terminal output conventions to print the completed move and warnings, including the relevant paths. Keep exit success for a committed move with cleanup warnings. Extend the mounted command tests to assert the warning and committed status independently of terminal styling. The command's human-readable output gains content.

## Cleanup

<a id="csc-09"></a>

### CSC-09 · P3 · Remove obsolete pre-activation Windows registration rollback

**Evidence and impact.** Managed installation initializes its local Windows registration snapshot to `None` and never assigns it. Editable registration passes `None` directly. The shared failure handler still advertises and implements restoration for that parameter. Both callers now publish Windows Installed apps registration after committing installation authority. Development still describes restoration of captured Windows registration as part of pre-activation rollback. [Unused restoration branch](src/apprc/distribution/runtime/installation.py#L1058) · [Managed caller](src/apprc/distribution/runtime/installation.py#L1300) · [Editable failure path](src/apprc/distribution/runtime/installation.py#L2479) · [Development](docs/Development.md#source-ownership)

**Correction and verification.** Remove the unreachable installer parameter and branch and describe post-commit registration recovery in Development. Keep the Windows registration journal and the live uninstall restoration path. Verify managed and editable rollback plus the retained Windows fixture coverage. Record checkpoints are part of saved authority and do not need renaming for this cleanup. Native Windows validation remains deferred. [Registration recovery](src/apprc/distribution/runtime/_windows_registration.py#L166) · [Live uninstall caller](src/apprc/distribution/runtime/uninstall_handoff.py#L1468)

<a id="csc-10"></a>

### CSC-10 · P3 · Retire the deprecated `shared_default` keyword

**Evidence and impact.** `rc.field` accepts both `packaged_default` and its deprecated alias `shared_default`, including a conflict branch. Repository search found the old keyword in its implementation, a compatibility test, and changelog history. Current guides and examples use the canonical keyword. The alias adds a second spelling for the same field metadata. [Public field signature](src/apprc/public/field.py#L84) · [Alias handling](src/apprc/public/field.py#L152) · [Compatibility case](tests/public/test_app_rc_public_api.py#L365)

**Correction and verification.** If accepted for a breaking release, replace `shared_default=` with `packaged_default=` in consuming apps and document the migration. Existing callers using the alias would receive a `TypeError` until updated. Persisted dotenv files need no migration. Check known consumers before scheduling removal because this checkout cannot establish downstream use. Keep test coverage for the canonical keyword and remove only the alias-specific example.

The duplicate JSON-key checks in the uninstall handoff and namespace finalizer serve distinct execution contexts. The finalizer is staged and can run outside the installed AppRC package after retirement, so sharing parsing code there would require verifying both execution contexts. Workspace and secret migration code likewise retain active callers and user data contracts. [Standalone staging](src/apprc/distribution/runtime/uninstall_handoff.py#L1564) · [Migration guide](docs/How-To-User-Guides.md#migrate-existing-applications)

## Deeper edge cases

<a id="csc-11"></a>

### CSC-11 · P1 · Restrict failed workspace move cleanup to operation-owned paths

**Evidence and impact.** Cross-filesystem move prepares a private staging directory. Its exception handler chooses the destination as the cleanup candidate if that path exists, even if the rename of staging never succeeded. The destination can appear after the initial check, including when another filesystem writer creates it while a copy is underway. That writer does not necessarily participate in AppRC's locks. A copy or publication failure can then cause cleanup to remove the unrelated directory and its contents. [Destination check](src/apprc/user_files/workspace_roots/move.py#L83) · [Copy and rollback](src/apprc/user_files/workspace_roots/move.py#L217)

**Correction and verification.** Track publication explicitly and restrict recursive cleanup to the directory whose identity AppRC created. Preserve the source and any unrelated destination when publication fails. Keep the existing registry rollback for an owned publication. Add a deterministic failure-path regression with temporary directories for the copy branch. The existing move tests exercise the normal move and a registry write failure using same-filesystem temporary paths. The fix fits the existing API. [Move tests](tests/test_workspace_move.py)

<a id="csc-12"></a>

### CSC-12 · P2 · Validate the workspace root again after acquiring move locks

**Evidence and impact.** `WorkspaceManager.move_workspace` reads the registry and locks the selected source. The lower-level move reads the registry again and takes the current source from that read. If a concurrent repoint or move wins the registry lock first, the second read can select a different root. The queued move can then move data from a root the original request did not validate or lock. Archive and unregister also capture registry entries before waiting and warrant checking their own freshness semantics. [Manager capture and lock](src/apprc/services/workspaces.py#L262) · [Second registry read](src/apprc/user_files/workspace_roots/move.py#L58)

**Correction and verification.** Compare the captured record or root with the current value under the registry lock and require a fresh command if it changed. Keep the established lock order and path validation. Add a deterministic test for a repoint that wins while a move waits. Rejecting the stale operation changes failure behavior while preserving the API and file formats.

<a id="csc-13"></a>

### CSC-13 · P2 · Derive secret migration revisions from the bytes used to plan

**Evidence and impact.** `plan_secret_migration` reads the ordinary and private dotenv text and builds replacement documents before calling `file_revision`, which rereads each path. A write between those reads can attach a newer revision to an older document. The apply step trusts that revision under the write lock, so it can overwrite the intervening edit. The single dotenv edit planner already derives the text and revision from one byte capture. [Migration planning and apply](src/apprc/user_files/env_files/secret_migration.py#L50) · [Revision reader](src/apprc/user_files/app_home/writes.py#L146) · [Single edit baseline](src/apprc/user_files/env_files/updates.py#L245)

**Correction and verification.** Derive both planned text and digests from the same bytes for each path, preserving the missing-file distinction and newline behavior. Keep the locked apply check and private-first ordering. Add a regression for a write during planning that makes the plan stale. The distinct question of literal secret interpolation stays in its existing backlog issue. [Literal secret interpolation](BACKLOG.md#p2--e2-bug-risk---literal-secret-interpolation-needs-an-explicit-contract)

## Verification and coverage limits

| Check | Result on the reviewed source |
| --- | --- |
| `.venv/bin/pytest -q` | 1,158 passed, 40 skipped. Three Python 3.14 warnings about forking a multithreaded test process. |
| `TOGA_BACKEND=toga_dummy .venv/bin/pytest -q src/apprc_dev/packaging/gui/tests/test_view.py` | Eight passed. |
| `.venv/bin/apprc-examples-run-all` | All eight examples passed and removed their temporary resources. |
| `.venv/bin/ruff check .` and `.venv/bin/ruff format . --check` | Passed. |
| `.venv/bin/pyright` | Zero errors and three Windows-only import warnings on Linux. |
| `just --summary` and `uv lock --check --offline` | Passed. |
| Fresh-process CLI checks | Developer scaffold help and mounted workspace move, paths, and setup help rendered. The main suite also covered lazy import behavior. |

The installation review followed operation planning, publication before-images, revision-checked activation, caught rollback, post-commit cleanup, lease handling, and saved uninstall handoff. The existing uninstall resource admission issue remains a separate coordination problem. The workspace and dotenv review followed public managers through locking, revision and ownership checks, and file changes. The review checked matching CLI and editor consumers, functional and architecture tests, and documentation for these routes. [Uninstall resource admission](BACKLOG.md#p1--e1-bug-risk---uninstall-cleanup-can-race-with-new-resource-leases)

The edge-case findings are static evidence, and the follow-up tests listed with them are pending. Native Windows/macOS, opt-in PyApp installer execution, Gradio browser interaction (Chromium absent), hosted workflow execution, live release publishing, and downstream app migrations are outside the executed checks. No performance benchmark was run. [Deferred native validation](BACKLOG.md#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)
