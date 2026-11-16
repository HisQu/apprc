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
2. [2026-11-16](#2026-11-16)
   1. [P1 / E1 \[Bug risk\] - *Uninstall cleanup can race with new resource leases*](#p1--e1-bug-risk---uninstall-cleanup-can-race-with-new-resource-leases)
   2. [P2 / E2 \[Bug risk\] - *Literal secret interpolation needs an explicit contract*](#p2--e2-bug-risk---literal-secret-interpolation-needs-an-explicit-contract)
3. [2026-11-13](#2026-11-13)
   1. [P2 / E2 \[Bug risk\] - *Metadata-only version commands resolve appdata ownership*](#p2--e2-bug-risk---metadata-only-version-commands-resolve-appdata-ownership)
4. [2026-11-09](#2026-11-09)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)


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

<br>

# 2026-11-13

## P2 / E2 [Bug risk] - *Metadata-only version commands resolve appdata ownership*
- **Area:** `src/apprc/interfaces/cli/runtime.py`, `src/apprc/interfaces/cli/context.py`, and `src/apprc/user_files/installation/validation.py`.
- **Observed while:** Running an installed application's metadata-only `version` command with AppRC 0.34.0.
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
- **Suggested next step:** Leave the native jobs disabled while this work is deferred. Revisit when Windows/macOS validation is explicitly back in scope, starting with the recorded installation/ACL and standalone dependency failures, then path/interpreter and secret/UI workflows. Preserve containment and private-permission contracts; do not introduce runner, billing, or security changes implicitly.

<br>
