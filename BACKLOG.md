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
2. [2026-11-10](#2026-11-10)
   1. [P3 / E1 \[Code smell\] - *Saved management code doubles as installation configuration*](#p3--e1-code-smell---saved-management-code-doubles-as-installation-configuration)
3. [2026-11-09](#2026-11-09)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)


<br>

# 2026-11-10

Reviewed AppRC `0.32.0` at `aaeefe`. These findings concern maintenance and relearning cost, not confirmed runtime failures. Follow-up work must preserve independent optional capabilities and the existing ownership, revision, permission, and recovery guarantees.

## P3 / E1 [Code smell] - *Saved management code doubles as installation configuration*
- **Area:** `src/apprc/distribution/rendering.py`, `src/apprc/distribution/runtime/installation.py`, `src/apprc/distribution/runtime/launcher.py`, `src/apprc/distribution/standalone.py`
- **Observed while:** Following generated launch/uninstall support into runtime binding.
- **Why not fixed now:** This changes the saved-support format and bootstrap boundary, not just presentation or naming.
- **Evidence:** [`_launcher_script()` and `_uninstaller_script()`](src/apprc/distribution/rendering.py#L436-L634) embed executable management policy in strings. [`bind_install_support()`](src/apprc/distribution/runtime/installation.py#L826-L859) recovers the interpreter by scanning saved Python for `BASE_PYTHON = `, then [binds new output](src/apprc/distribution/runtime/installation.py#L885-L891) by replacing an exact quoted placeholder. [`runtime/launcher.py`](src/apprc/distribution/runtime/launcher.py) implements another launcher, but is absent from the [standalone closure](src/apprc/distribution/standalone.py#L14-L44); repository searches found no caller outside its own entry point.
- **Context:** Executable syntax is also a data protocol, so a harmless-looking rendering change can require changes in runtime binding. The apparently natural launcher module is not the shipped implementation. The stdlib-only bootstrap boundary is justified; hiding that boundary inside generated strings is not required by it.
- **Suggested next step:** Use canonical stdlib-only source files for saved management programs, following the existing `namespace_finalizer.py` approach. Keep interpreter settings as explicit owned, digest-covered support data rather than parsing Python source. Adopt or remove the unused launcher so one implementation remains. Preserve interpreter validation, saved backend selection, and previews that do not provision anything. Installation records remain the sole authority; owned support data must not become a second authority.

<br>

# 2026-11-09

<a id="p2--e1-tooling---windows-and-macos-installation-ci-fails"></a>

## P3 / E1 [Tooling] - *Windows and macOS installation validation is deferred*
- **Area:** `src/apprc/distribution/runtime`, `src/apprc/user_files/app_home/locations.py`, `src/apprc/interfaces/tui`, and their native tests.
- **Observed while:** Inspecting automatic [push CI run 42605623620](https://github.com/HisQu/apprc/actions/runs/42605623620) for `661738`.
- **Why not fixed now:** Explicitly deferred by the user. Keep CI Linux-only; native remediation is not a prerequisite for Linux releases or the current maintainability work.
- **Evidence:** Windows core/GUI and macOS core jobs failed while Ubuntu core Python 3.12/3.13/3.14 and Ubuntu GUI passed. Representative failures include Windows private staging ACL rejection, missing `ntsecuritycon` in standalone execution, macOS temporary-address link rejection, and native secret persistence/editor workflows.
- **Context:** The historical native failures remain unresolved; disabling their jobs did not fix them or establish compatibility. Their causes have not yet been separated into production defects, fixture/platform assumptions, interpreter prerequisites, newline expectations, or shell setup. Permission rejection alone is not evidence of a security vulnerability.
- **Suggested next step:** Leave the native jobs disabled while this work is deferred. Revisit when Windows/macOS validation is explicitly back in scope, starting with the recorded installation/ACL and standalone dependency failures, then path/interpreter and secret/UI workflows. Preserve containment and private-permission contracts; do not introduce runner, billing, or security changes implicitly.

<br>
