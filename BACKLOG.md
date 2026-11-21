# Backlog

Treat this as the parking lot for actionable problems discovered while working but intentionally left unresolved.


<br>

> [!CAUTION]
> This is git-tracked: Never record secrets, absolute paths, credentials, private host data, or speculative security claims. Use only relative paths. 


> [!IMPORTANT]
> 
> ## Rules
> 1) Do not remove or change this header and TOC without very good reason. 
> 1) Newest at the top.
> 1) Append a new entry only when the observation is real, actionable, not already listed, and out of scope for the current change. Do not modify `BACKLOG.md` when there is nothing useful to add.
> 1) If an issue is new and related to another issue, reference it in the `Suggested next step`. Do not create a new entry for the same problem. Place the reference in both entries (bi-directional).
> 1) If an issue was resolved, remove it. Add a CHANGELOG.md entry only when the change has a notable user- or contributor-facing effect.
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
> - **Suggested next step:** smallest reasonable follow-up. If applicable, reference related backlog items [here](#backlog).
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

1. [Backlog](#backlog)
   1. [Table Of Contents](#table-of-contents)
2. [2026-11-21](#2026-11-21)
   1. [P1 / E1 \[Bug risk\] - *Keep workspace move rollback within owned paths*](#p1--e1-bug-risk---keep-workspace-move-rollback-within-owned-paths)
   2. [P2 / E2 \[Bug risk\] - *Derive secret migration revisions from the planned bytes*](#p2--e2-bug-risk---derive-secret-migration-revisions-from-the-planned-bytes)
   3. [P2 / E2 \[Bug risk\] - *Resume an editable update after partial completion*](#p2--e2-bug-risk---resume-an-editable-update-after-partial-completion)
   4. [P2 / E3 \[Code smell\] - *Surface workspace move warnings in the CLI*](#p2--e3-code-smell---surface-workspace-move-warnings-in-the-cli)
   5. [P2 / E1 \[Code smell\] - *Simplify installer activation and remove obsolete rollback*](#p2--e1-code-smell---simplify-installer-activation-and-remove-obsolete-rollback)
   6. [P2 / E1 \[Code smell\] - *Unify internal CLI command classification*](#p2--e1-code-smell---unify-internal-cli-command-classification)
   7. [P2 / E2 \[Code smell\] - *Capture one target for grouped configuration edits*](#p2--e2-code-smell---capture-one-target-for-grouped-configuration-edits)
   8. [P3 / E2 \[Code smell\] - *Group dependency configuration tests by contract*](#p3--e2-code-smell---group-dependency-configuration-tests-by-contract)
   9. [P3 / E1 \[Code smell\] - *Bound source snapshot memory*](#p3--e1-code-smell---bound-source-snapshot-memory)
   10. [P3 / E3 \[Docs drift\] - *Document the current hosted CI profiles*](#p3--e3-docs-drift---document-the-current-hosted-ci-profiles)
   11. [P3 / E3 \[Question\] - *Decide when to retire shared_default*](#p3--e3-question---decide-when-to-retire-shared_default)
3. [2026-11-18](#2026-11-18)
   1. [P3 / E3 \[Bug risk\] - *Verify managed desktop shortcuts on Windows*](#p3--e3-bug-risk---verify-managed-desktop-shortcuts-on-windows)
   2. [P3 / E3 \[Tooling\] - *Hosted distribution CLI tests depend on terminal formatting*](#p3--e3-tooling---hosted-distribution-cli-tests-depend-on-terminal-formatting)
4. [2026-11-16](#2026-11-16)
   1. [P1 / E1 \[Bug risk\] - *Uninstall cleanup can race with new resource leases*](#p1--e1-bug-risk---uninstall-cleanup-can-race-with-new-resource-leases)
   2. [P2 / E2 \[Bug risk\] - *Literal secret interpolation needs an explicit contract*](#p2--e2-bug-risk---literal-secret-interpolation-needs-an-explicit-contract)
5. [2026-11-13](#2026-11-13)
   1. [P2 / E2 \[Bug risk\] - *Metadata-only version commands resolve appdata ownership*](#p2--e2-bug-risk---metadata-only-version-commands-resolve-appdata-ownership)
6. [2026-11-09](#2026-11-09)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)


<br>

# 2026-11-21

## P1 / E1 [Bug risk] - *Keep workspace move rollback within owned paths*

- **Area:** `src/apprc/user_files/workspace_roots/move.py` and `src/apprc/services/workspaces.py`
- **Observed while:** Tracing copy failures and queued moves in the CSC.
- **Why not fixed now:** The fixes need deterministic coverage for cross-filesystem failure and lock ordering.
- **Evidence:** Copy rollback uses destination existence to decide what to remove. The manager locks one source root, while the move can read a different root from the registry later. [CSC-11](code-smells.md#csc-11) · [CSC-12](code-smells.md#csc-12)
- **Context:** A failed copy can remove an unrelated destination. A concurrent repoint can change the root before the move uses it.
- **Suggested next step:** Track the identity of the published directory and compare the workspace record under lock. Cover the two failure paths and preserve the [CLI cleanup warnings](#p2--e3-code-smell---surface-workspace-move-warnings-in-the-cli).

<br>

## P2 / E2 [Bug risk] - *Derive secret migration revisions from the planned bytes*

- **Area:** `src/apprc/user_files/env_files/secret_migration.py`
- **Observed while:** Comparing secret migration and ordinary dotenv edit planning.
- **Why not fixed now:** The migration write change needs a focused stale-plan regression.
- **Evidence:** Migration computes the replacement documents before rereading both files for their revisions. [CSC-13](code-smells.md#csc-13)
- **Context:** The locked apply step can accept an older plan that carries a newer revision.
- **Suggested next step:** Derive text and revisions from one capture per file and verify that an intervening write makes the plan stale. Keep the [literal interpolation decision](#p2--e2-bug-risk---literal-secret-interpolation-needs-an-explicit-contract) separate from this write-safety fix.

<br>

## P2 / E2 [Bug risk] - *Resume an editable update after partial completion*

- **Area:** `src/apprc/distribution/runtime/update.py` and `src/apprc/distribution/runtime/_update_handoff.py`
- **Observed while:** Tracing editable update failure and retry.
- **Why not fixed now:** Retrying needs a way to identify outstanding registration.
- **Evidence:** The up-to-date check uses Git and dependency sync. Registration can fail after both have succeeded. [CSC-07](code-smells.md#csc-07)
- **Context:** The failed command prints a direct retry. A repeat update can skip the registration step.
- **Suggested next step:** Check whether existing installation evidence can establish registration freshness. Verify a retry after a simulated failure between sync and registration and show the remaining recovery commands.

<br>

## P2 / E3 [Code smell] - *Surface workspace move warnings in the CLI*

- **Area:** `src/apprc/interfaces/cli/maintenance_command.py`
- **Observed while:** Comparing CLI and Textual workspace moves.
- **Why not fixed now:** The command output change needs an explicit fixture for a committed move with cleanup remaining.
- **Evidence:** The CLI discards `WorkspaceMoveResult`, while Textual displays its warnings. [CSC-08](code-smells.md#csc-08)
- **Context:** The service already distinguishes a completed move from its best-effort source cleanup.
- **Suggested next step:** Report the new root and warnings through shared terminal output. Reuse the result when verifying [workspace rollback ownership](#p1--e1-bug-risk---keep-workspace-move-rollback-within-owned-paths).

<br>

## P2 / E1 [Code smell] - *Simplify installer activation and remove obsolete rollback*

- **Area:** `src/apprc/distribution/runtime/installation.py`
- **Observed while:** Following managed setup, editable registration, and caught-failure restoration.
- **Why not fixed now:** Activation changes need the existing checkpoint and rollback suite plus targeted Windows fixtures.
- **Evidence:** Managed and editable paths repeat activation orchestration. Both always pass `None` to a rollback parameter for Windows registration, which now runs after commit. [CSC-01](code-smells.md#csc-01) · [CSC-09](code-smells.md#csc-09)
- **Context:** The installation file combines preparation, publication, recovery, and user-facing setup. The obsolete branch obscures the commit boundary.
- **Suggested next step:** Delete the unreachable branch and correct Development. Then consolidate the shared activation sequence while keeping both preparation paths and live uninstall recovery explicit.

<br>

## P2 / E1 [Code smell] - *Unify internal CLI command classification*

- **Area:** `src/apprc/interfaces/cli/runtime.py`
- **Observed while:** Following CLI help, installation commands, diagnostic commands, and host runtime setup.
- **Why not fixed now:** Several command identities and option-separator cases need behavior-preserving coverage.
- **Evidence:** Runtime preparation repeats nested action parsing across multiple predicates and handles generated command identity in separate branches. [CSC-02](code-smells.md#csc-02)
- **Context:** An added route can affect which context a command receives and whether help imports runtime code.
- **Suggested next step:** Consolidate internal classification with the existing argument parser and verify aliases, host collisions, and fresh-process help.

<br>

## P2 / E2 [Code smell] - *Capture one target for grouped configuration edits*

- **Area:** `src/apprc/services/manager.py`
- **Observed while:** Following grouped settings from field planning to managed file writes.
- **Why not fixed now:** Capturing the target once needs a test for changing workspace selection during planning.
- **Evidence:** Each field repeats workspace inspection and secret fields repeat privacy checks. [CSC-04](code-smells.md#csc-04)
- **Context:** Repeated reads increase the work per field and allow a batch using implicit selection to capture different roots.
- **Suggested next step:** Capture the workspace and file destinations once, then reuse them for field-specific validation and revision checks.

<br>

## P3 / E2 [Code smell] - *Group dependency configuration tests by contract*

- **Area:** `tests/public/test_dependency_config_import.py`
- **Observed while:** Following the tested registration, resolution, and bundle contracts.
- **Why not fixed now:** This is an independent test organization change.
- **Evidence:** A 1,613-line module mixes registration rollback, resolution precedence, lifecycle behavior, and bundles. [CSC-03](code-smells.md#csc-03)
- **Context:** The cases cover distinct contracts and can be easier to locate.
- **Suggested next step:** Move cases into focused test modules, preserve assertions, and compare collection before and after.

<br>

## P3 / E1 [Code smell] - *Bound source snapshot memory*

- **Area:** `src/apprc/distribution/project.py` and `src/apprc/distribution/_archives.py`
- **Observed while:** Tracing committed source export and snapshot validation.
- **Why not fixed now:** Archive byte reproducibility and actual memory savings need verification.
- **Evidence:** The snapshot path buffers the Git tar, input file bytes, and compressed ZIP in memory. [CSC-05](code-smells.md#csc-05)
- **Context:** Larger prepared assets increase peak memory during a local build.
- **Suggested next step:** Measure a representative large snapshot and stream the project archive through the existing private stage while preserving its exact bytes and checks.

<br>

## P3 / E3 [Docs drift] - *Document the current hosted CI profiles*

- **Area:** `docs/Development.md` and `.github/workflows/ci.yml`
- **Observed while:** Comparing documented verification with the profile job.
- **Why not fixed now:** This CSC records changes for follow-up.
- **Evidence:** Ordinary core runs use Python 3.12. Extended release runs add 3.13 and 3.14 and use 3.14 for GUI checks. [CSC-06](code-smells.md#csc-06)
- **Context:** The guide gives a single matrix and mentions the prior GUI version.
- **Suggested next step:** Describe each active profile and how to interpret a green run while retaining the [native platform coverage issue](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred).

<br>

## P3 / E3 [Question] - *Decide when to retire shared_default*

- **Area:** `src/apprc/public/field.py`
- **Observed while:** Reviewing deprecated parameters and their callers.
- **Why not fixed now:** Alias removal is a breaking public API change.
- **Evidence:** The deprecated `shared_default` keyword is still accepted alongside `packaged_default`. [CSC-10](code-smells.md#csc-10)
- **Context:** Repository usage is limited to compatibility coverage and history. External app usage is unknown.
- **Suggested next step:** Check consumers and decide on a breaking release window. Any affected caller can use `packaged_default` directly.

<br>

# 2026-11-18

## P3 / E3 [Bug risk] - *Verify managed desktop shortcuts on Windows*
- **Area:** `src/apprc/distribution/runtime/_manager.py` and `src/apprc/distribution/runtime/_os_integration.py`.
- **Observed while:** Adding the desktop shortcut prompt to managed setup.
- **Why not fixed now:** Native Windows execution is unavailable in the current environment.
- **Evidence:** AppRC stages a new `.lnk` before publishing it. The automated test uses a stand-in for Windows Script Host.
- **Suggested next step:** On native Windows, verify shortcut creation, launch, and cleanup for managed and editable installs. Check the icon in Windows Installed apps and the separate classic-console uninstall window. See the [deferred native installation checks](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred).

<br>

## P3 / E3 [Tooling] - *Hosted distribution CLI tests depend on terminal formatting*
- **Area:** `tests/test_cli_distribution.py`
- **Observed while:** Checking the merge of GitHub one-line install script generation. [Baseline run](https://github.com/HisQu/apprc/actions/runs/44367354562), [pull request run](https://github.com/HisQu/apprc/actions/runs/44377188297).
- **Why deferred:** The failures also occur on the pre-change revision. CLI output assertions are outside the script generation pass.
- **Evidence:** Three hosted tests fail to match `--target-current`, `uv sync --locked --all-groups`, or `app install --yes` in Rich output with ANSI formatting. All 11 distribution CLI tests pass in the local environment.
- **Context:** The tests check help and installer guidance as raw substrings, so a styling boundary or line wrap can break an assertion.
- **Suggested next step:** Make the assertions insensitive to ANSI formatting and line wrapping while retaining the checks for help text and lightweight startup.

<br>

# 2026-11-16

## P1 / E1 [Bug risk] - *Uninstall cleanup can race with new resource leases*
- **Area:** `src/apprc/distribution/runtime/uninstall_handoff.py`, `src/apprc/services/maintenance.py`, and application resource-admission callbacks.
- **Observed while:** Updating PersoDB to AppRC's whole-directory uninstall contract.
- **Why not fixed now:** Explicitly deferred by the user so the PersoDB update can proceed.
- **Evidence:** The uninstall controller invokes the application cleanup hook to check leases, then later drains resource locks and removes the selected directories. PersoDB has cache readers that acquire a lease under a resource lock without captured installation authority; such a reader can enter after the hook finishes. AppRC maintenance provider callbacks receive a path or plan, not the captured installation authority needed to reject that admission against the pending uninstall.
- **Context:** A new lease in this interval could leave a reader using files while uninstall removes their directory. Existing authority-bound admissions are rejected while the uninstall is pending. This is an observed coordination gap, not a demonstrated exploit.
- **Suggested next step:** Establish an authority-aware admission and cleanup contract that prevents new resource leases between the final lease check and whole-directory deletion, including direct consumers and maintenance callbacks. Add a deterministic multi-process regression for a reader queued across uninstall, and verify retries and release paths do not deadlock.

<br>

## P2 / E2 [Bug risk] - *Literal secret interpolation needs an explicit contract*
- **Area:** `src/apprc/user_files/env_files/values.py` and dotenv parsing/loading.
- **Observed while:** Reviewing grouped GS Online credential saving and checking.
- **Why not fixed now:** Changing existing global secret normalization or interpolation would expand the accepted grouped-edit feature into a configuration-policy change.
- **Evidence:** String normalization strips surrounding whitespace, and existing dotenv loading expands literal `${VAR}` text in saved quoted values. The credential UI now checks normalized new values and retains existing secrets without rewriting them, using the manager's captured environment for retained-secret parsing.
- **Context:** A newly entered literal secret containing interpolation syntax can differ when reloaded. This behavior predates grouped edits; no actual credentials or exploit are recorded here.
- **Suggested next step:** Define literal-secret storage and reload semantics separately from ordinary configuration interpolation, then add round-trip tests for whitespace, dollar/braced text, and captured-versus-ambient environments without exposing values.
- **Related:** [Secret migration revision binding](#p2--e2-bug-risk---derive-secret-migration-revisions-from-the-planned-bytes) covers concurrent file changes during planning.

<br>

# 2026-11-13

## P2 / E2 [Bug risk] - *Metadata-only version commands resolve appdata ownership*
- **Area:** `src/apprc/interfaces/cli/runtime.py`, `src/apprc/interfaces/cli/context.py`, and `src/apprc/user_files/installation/validation.py`.
- **Observed while:** Running an installed application's metadata-only `version` command with AppRC 0.34.0.
- **Recheck:** PersoDB's eager `--version` and `-V` bypass runtime preparation. Its existing regression passed with invalid settings and with and without unknown appdata. The original failure did not reproduce on these routes. AppRC's runtime-skip policy still resolves paths for host commands that use the prepared path context.
- **Why not fixed now:** The SDK release is already published. Changing CLI preparation needs a focused regression and an explicitly scoped maintenance change; existing application data must remain untouched.
- **Evidence:** The command raised `InstallationError: Nonempty native appdata container requires project-owned migration or adoption.` The same installed version query succeeded with an explicit fresh single-root layout.
- **Context:** CLI preparation resolves application paths before returning package metadata, so unrelated existing appdata can prevent a version query. The appdata ownership guard itself must remain strict.
- **Suggested next step:** Add an existing-suite CLI regression with an unknown appdata entry. Separate metadata-only command preparation from managed-path resolution without bypassing ownership checks for filesystem operations.

<br>

# 2026-11-09

<a id="p2--e1-tooling---windows-and-macos-installation-ci-fails"></a>

## P3 / E1 [Tooling] - *Windows and macOS installation validation is deferred*
- **Area:** `src/apprc/distribution/runtime`, `src/apprc/user_files/app_home/locations.py`, `src/apprc/interfaces/tui`, and their native tests.
- **Observed while:** Inspecting automatic [push CI run 42605623620](https://github.com/HisQu/apprc/actions/runs/42605623620) for `661738`.
- **Why not fixed now:** Explicitly deferred by the user. Keep CI Linux-only; native remediation is not a prerequisite for Linux releases or the current maintainability work.
- **Evidence:** Windows core/GUI and macOS core jobs failed while Ubuntu core Python 3.12/3.13/3.14 and Ubuntu GUI passed. Representative failures include Windows private staging ACL rejection, missing `ntsecuritycon` in standalone execution, macOS temporary-address link rejection, and native secret persistence/editor workflows.
- **Context:** The installation-rollback pass identified missing ACL application on operation-created bridge/project temporary directories and corrected those creation paths. Native Windows execution is still needed to establish that correction on Windows. The other historical native failures remain unresolved; disabling their jobs did not fix them or establish compatibility. Their causes have not yet been separated into production defects, fixture/platform assumptions, interpreter prerequisites, newline expectations, or shell setup. Permission rejection alone is not evidence of a security vulnerability.
- **Managed setup follow-up:** The PersoDB Windows setup traceback confirmed
  that creating a runtime source directory before the materializer skipped the
  private ACL helper. The materializer now owns directory creation, with a
  regression covering fresh extraction and rebuild. Native Windows verification
  of the rebuilt installer remains manual and deferred.
- **Suggested next step:** Leave the native jobs disabled while this work is deferred. Revisit when Windows/macOS validation is explicitly back in scope, starting with the recorded installation/ACL and standalone dependency failures, then path/interpreter and secret/UI workflows. Preserve containment and private-permission contracts; do not introduce runner, billing, or security changes implicitly.
- **Related:** The [desktop shortcut follow-up](#p3--e3-bug-risk---verify-managed-desktop-shortcuts-on-windows) covers native shortcut creation, launch, and removal.
- **Related:** [Hosted CI profile documentation](#p3--e3-docs-drift---document-the-current-hosted-ci-profiles) covers which Linux jobs the current workflow schedules.

<br>
