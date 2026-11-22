# 🔎 AppRC Code Smell Cleanup

**Goal**

Identify defects and cleanup opportunities that make AppRC easier to maintain and operate.

**Specifics**

Reviewed `main` at `11927a` (tree `3a0c57`) on Linux with Python 3.14.2. The review covered the SDK, CLI, Textual and Gradio interfaces, workspace and installation operations, packaging, workflows, docs, examples, and relevant tests. The user selected deeper edge cases and asked to consider breaking proposals.

The correctness pass fixed eight findings. The follow-up completed CSC-01, CSC-02, and CSC-03 and measured CSC-05 on PersoDB's release snapshot. The measurement and the decision to retain the compatibility alias are recorded below. [Backlog](BACKLOG.md)

| Finding | Disposition |
| --- | --- |
| [CSC-01](#csc-01) | Fixed. Managed and editable installation share the final activation steps. |
| [CSC-02](#csc-02) | Fixed. Runtime preparation uses one invocation classification. |
| [CSC-03](#csc-03) | Fixed. Registration, resolution, and binding cases live in separate modules. |
| [CSC-04](#csc-04) | Fixed. Grouped edits use one captured workspace and destination set. |
| [CSC-05](#csc-05) | Measured. Revisit if a larger workload shows a build constraint. |
| [CSC-06](#csc-06) | Fixed. Development documents the active CI profiles. |
| [CSC-07](#csc-07) | Fixed. A confirmed editable update refreshes registration when Git is current. |
| [CSC-08](#csc-08) | Fixed. The CLI reports the committed destination and cleanup warnings. |
| [CSC-09](#csc-09) | Fixed. The dead installer rollback path is removed. |
| [CSC-10](#csc-10) | Retained for public API compatibility. |
| [CSC-11](#csc-11) | Fixed. Rollback checks directory identity before moving or removing an owned path. |
| [CSC-12](#csc-12) | Fixed. The move rejects a changed workspace record after acquiring locks. |
| [CSC-13](#csc-13) | Fixed. Migration plans bind text and revision to the same byte capture. |

The original scan prioritized workspace move rollback, a queued move acting on a different source, and the secret migration snapshot. Source inspection identified those interleavings. The correctness pass subsequently added regression cases that failed on the baseline and passed with the fixes. [CSC-11](#csc-11) · [CSC-12](#csc-12) · [CSC-13](#csc-13)

## Obvious bugs

The baseline and example smoke checks exercised ordinary configuration, workspace selection, scaffold, CLI help and diagnostics, and fixture-backed installation and recovery. They exposed no primary success-path failure. The findings below identify concrete behavior in failure paths, plus maintainability and documentation improvements.

## Code smells

<a id="csc-01"></a>

### CSC-01 · P3 · Make managed and editable activation easier to trace

**Evidence and impact.** Managed and editable installation each repeated the final checkpoints, installation authority commit, Windows registration, and finalization. A change to those steps required tracing both paths and their shared recovery function.

**Correction and verification.** Managed and editable callers share the final checkpoints, activation commit, and post-commit registration and finalization. Each caller prepares its candidate and publishes its command using its existing before-images and output ordering. The installer and rollback tests exercise both paths. [Activation](src/apprc/distribution/runtime/installation.py#L1262) · [Rollback tests](tests/test_installation_rollback.py)

## Intuitive code traversal

<a id="csc-02"></a>

### CSC-02 · P3 · Give CLI command classification one internal entry point

**Evidence and impact.** Installation, diagnostic, and runtime-skip predicates each inspected the current arguments. Determining which context a command received meant tracing those predicates alongside the callback identity checks that distinguish generated commands from host commands with the same name.

**Correction and verification.** Runtime preparation captures the current or forwarded tokens once and classifies them using the existing parsers. Built-in policies reuse the located child arguments when applicable. Runtime and integration tests cover host command identity, custom group names, option separators, and lightweight fresh-process help. [Classification](src/apprc/interfaces/cli/runtime.py#L715) · [Runtime tests](tests/test_cli_runtime.py) · [Fresh-process distribution help](tests/test_cli_distribution.py#L107)

<a id="csc-03"></a>

### CSC-03 · P3 · Group dependency configuration tests by contract

**Evidence and impact.** The original dependency import module mixed registration and rollback, resolution precedence and workspace requirements, and binding lifecycle. Cases with different fixture shapes were difficult to locate in one file.

**Correction and verification.** The three modules group cases by contract. Declarations used in multiple modules live in test support. The split preserves the source of all 31 test functions and decorators and all 33 collected cases, including parametrization. All 88 public API tests passed. [Registration](tests/public/test_dependency_config_registration.py) · [Resolution](tests/public/test_dependency_config_resolution.py) · [Binding](tests/public/test_dependency_config_binding.py) · [Shared declarations](tests/support_dependency_config.py)

## Code efficiency

<a id="csc-04"></a>

### CSC-04 · P2 · Capture a workspace target once for a grouped settings edit

**Evidence and impact.** Each field in `plan_updates` resolves its declaration and calls `plan_update`. Each secret also repeats private-file checks. Resolving a workspace write path invokes full configuration inspection, so a single grouped write may reload and inspect the same workspace several times. An implicit selection can also change while the batch is being planned because each field selects its own target. [Workspace write path](src/apprc/services/manager.py#L177) · [Single and grouped planning](src/apprc/services/manager.py#L296) · [Secret check](src/apprc/services/manager.py#L441)

**Correction and verification.** Capture the selected workspace and writable paths per operation, then reuse them for field validation and revision-checked writes. Keep private and ordinary destinations separate. Add coverage for changing an implicit workspace selection during planning and compare inspection call counts for a mixed batch. Existing grouped-write tests cover rollback. The expected benefit is fewer inspections and a single target per batch. The size of the runtime improvement is unmeasured. [Batch tests](tests/test_config_batch_updates.py)

<a id="csc-05"></a>

### CSC-05 · P3 · Bound source snapshot memory

**Evidence and impact.** The source-build path captures the whole Git tar in memory before writing it to the private stage. It later retains each input file's bytes, the ZIP buffer, and the completed ZIP bytes. The full input and archive sizes contribute to peak memory, especially for projects with large prepared assets. Native product assembly also uses the deterministic ZIP helper, so changing its contract for all callers would widen the work. [Project staging](src/apprc/distribution/project.py#L379) · [Snapshot assembly](src/apprc/distribution/project.py#L428) · [ZIP helper](src/apprc/distribution/_archives.py#L10)

**Measurement and disposition.** Three Linux runs built the source snapshot for PersoDB revision `845454` into separate temporary directories. Each took 0.24 seconds of wall time. GNU `time` reported peaks of 54,920, 54,896, and 54,896 KiB RSS for the Python process, including imports. Each ZIP was 1,884,796 bytes with SHA-256 `d7c67a60524f09356e9996d11c1db568b159d5785e8a004a189a13e3dfc804c8`. This release workload did not justify changing the implementation. Revisit with larger prepared assets if memory becomes a build constraint and compare peak RSS and archive bytes. [Snapshot tests](tests/test_project_snapshot.py)

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

**Disposition.** Retain the alias for compatibility and use `packaged_default=` in new code. If a future breaking release has a reason to remove it, check known consumers and document the keyword migration. Existing callers using the alias would receive a `TypeError` until updated. Persisted dotenv files need no migration.

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

**Correction and verification.** Derive both planned text and digests from the same bytes for each path, preserving the missing-file distinction and newline behavior. Keep the locked apply check and private-first ordering. Add a regression for a write during planning that makes the plan stale. The later backlog pass established a separate contract for newly entered literal secrets. [Secret companions](docs/Explanations.md#secret-companions)

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

The installation review followed operation planning, publication before-images, revision-checked activation, caught rollback, post-commit cleanup, lease handling, and saved uninstall handoff. The later backlog pass addressed the uninstall resource admission issue with PersoDB. The workspace and dotenv review followed public managers through locking, revision and ownership checks, and file changes. The review checked matching CLI and editor consumers, functional and architecture tests, and documentation for these routes. [Installation and resource coordination](docs/Development.md#source-ownership)

The scan began with source evidence for the edge cases. The correctness pass records its additional tests separately. The initial scan used Linux fixtures, skipped opt-in PyApp and browser checks, and did not benchmark performance. [Pass checklist](TODO.md) · [Deferred native validation](BACKLOG.md#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)

## CSC-14 through CSC-28 follow-up

**Goal.** Resolve the actionable findings from the deeper review at `b1b5e0`.
The implementation pass started at `4e37da`, which contains the original
backlog evidence. The prior Windows and macOS deferral still applies.

| Finding | Disposition and verification |
| --- | --- |
| <a id="csc-14"></a>CSC-14 · Inherited slots | Assignment recognizes inherited slots even when a config also has an instance dictionary. Copy and scoped overrides keep manually declared private slots. [Config lifecycle cases](tests/test_base_config.py) |
| <a id="csc-15"></a>CSC-15 · Gradio workspace capture | Each render binds the displayed settings and built-in edits to the inspected directory. Explicit browser choices update the saved default and stay specific to that session. The browser regression covers external default changes, a repointed workspace name, and saves from two sessions. [Gradio browser test](src/apprc_dev/packaging/gui/tests/test_browser_interactivity.py) |
| <a id="csc-16"></a>CSC-16 · Command publication | Managed and editable routes share publication, before-images, resume, rollback, and image cleanup. The authority sequence and saved formats retain their existing contracts. [Publication](src/apprc/distribution/runtime/_command_publication.py) · [Rollback tests](tests/test_installation_rollback.py) |
| <a id="csc-17"></a>CSC-17 · uv workspace patterns | The checkout and snapshot routes share parsing and root-relative expansion. Each keeps its existing hidden-path, containment, and member metadata rules. A staging parent with literal brackets now gives the same snapshot bytes. [Checkout cases](tests/test_installation_source_identity.py) · [Snapshot authoring cases](tests/test_project_authoring.py) |
| <a id="csc-18"></a>CSC-18 · Installation diagnostics | Mounted installation and doctor commands use one inspection projection. The JSON fields and lazy CLI loading behavior stay compatible. [CLI output](src/apprc/interfaces/cli/_installation_output.py) · [Doctor tests](tests/test_cli_doctor_installation.py) |
| <a id="csc-19"></a>CSC-19 · Native lifecycle cases | Separately selectable cases cover build artifacts, diagnostics, editable registration, and config retention. The cumulative case keeps repair, update, runtime lease, cleanup retry, and both temporary-path variants. [Native lifecycle tests](tests/test_distribution_pyapp.py) |
| <a id="csc-20"></a>CSC-20 · Settings field lookup | Owner-wide loops reuse resolved field metadata. On Linux with Python 3.14.2, binding a synthetic 1,000-field owner took 27.4 ms before the change and 10.2 ms after it, using `timeit` with 10 loops and the best of five repetitions. This measures binding for that workload. [Binding cases](tests/public/test_dependency_config_binding.py) |
| <a id="csc-21"></a>CSC-21 · Snapshot metadata walks | Configuration and lock metadata are gathered in one pruned walk before preparation and one after it. Existing separate diagnostics cover both; a new test checks that a nested lock introduced during preparation is rejected. [Authoring cases](tests/test_project_authoring.py) |
| <a id="csc-22"></a>CSC-22 · Gradio constructor documentation | Explanations uses the implemented constructor. The root README also describes the current CI profiles and links to Development. [Gradio editor](docs/Explanations.md#gradio-editor) · [CI profiles](docs/Development.md#environment) |
| <a id="csc-23"></a>CSC-23 · Retry command output | Sync and registration recovery put the command on its own line without punctuation. POSIX tests parse commands whose paths contain spaces and apostrophes, and the mounted CLI keeps the command intact at narrow terminal widths. The PowerShell quoting path is unchanged. [Update tests](tests/test_distribution_update.py) · [Mounted CLI cases](tests/test_cli_installation.py) |
| <a id="csc-24"></a>CSC-24 · Reconnect prompts | Textual and CLI help explain that reconnect can initialize the ordinary settings file. The editor test starts with an uninitialized directory. [Textual test](tests/test_config_tui_editor.py) |
| <a id="csc-25"></a>CSC-25 · Archive prune | Removed the unused internal operation. Missing and explicitly removed archive entries retain their existing UI behavior. [Workspace registry](src/apprc/user_files/workspace_roots/registry.py) |
| <a id="csc-26"></a>CSC-26 · Locked workspace records | Archive, restore, and unregister reject stale registry records once locked. Restore compares the consumed archive row and also the source row when the registry supplied the archive. [Workspace cases](tests/test_workspace_archive.py) |
| <a id="csc-27"></a>CSC-27 · Committed workspace outcomes | Unavailable private companions and expected setup exceptions produce repair guidance while preserving committed register and restore results. [Workspace cases](tests/test_workspace_archive.py) |
| <a id="csc-28"></a>CSC-28 · Coordination process start | The three finalization tests start isolated child processes and retain their deterministic pipe barriers. [Coordination tests](tests/test_installation_finalization_coordination.py) |

The opt-in Linux PyApp suite passed all 23 installation and recovery cases on
the initial implementation, including both managed temporary-path variants.
The final review added the mounted CLI retry and browser repoint regressions.
[Native verification procedure](docs/Development.md#verify-an-application-distribution)
