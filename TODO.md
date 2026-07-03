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
   1. [2026-07-03](#2026-07-03)


<br>

# 2026-07-03

## P2 / E2 [Tooling] - *PyPI verification helper checks removed root API*
- **Area:** `justfile:verify-pypi`
- **Observed while:** pre-release bug and code-smell audit after moving the TUI behind the optional `tui` extra
- **Why not fixed now:** this needs a small release-workflow decision about whether the helper should verify the published package, the local checkout, or both
- **Evidence:** `just verify-pypi` still runs `python -c 'import apprc; print(apprc.AppConfigKit)'`, but the current public root facade intentionally does not export `AppConfigKit`.
- **Context:** The helper is meant to validate a fresh plain-pip install before or after publishing. As written, it will fail for the new clean root facade even when the package install is healthy, which can block or confuse release verification.
- **Suggested next step:** Update the helper to check stable public root names such as `apprc.AppRC`, `apprc.Config`, and `apprc.field`; add a no-extra smoke check for `import apprc` and, if desired, a separate `apprc[tui]` install check.

## P3 / E2 [Tooling] - *Nested stale egg-info survives cleanup*
- **Area:** `examples/example_apps/src/apprc_example_apps.egg-info`, `justfile:clean`
- **Observed while:** pre-release audit of stale example-package paths and generated artifacts
- **Why not fixed now:** deleting ignored local artifacts and changing cleanup behavior is useful but separate from the current release-surface audit
- **Evidence:** the current example package is named `apprc-example-apps`, but an ignored nested `apprc_example_apps.egg-info` directory still exists under the example source tree. `just clean` removes only root-level `*.egg-info`, not nested metadata directories.
- **Context:** Stale ignored package metadata can make IDEs, local import inspection, and manual debugging surface old package names even after the source package was renamed to `_example_apps_utils` plus short example app packages.
- **Suggested next step:** Make `just clean` remove nested `*.egg-info` directories with `find . -type d -name "*.egg-info" ...`, then delete the stale ignored metadata locally.

## P3 / E1 [Code smell] - *Lazy facade exports are duplicated for type checking*
- **Area:** `src/apprc/cli/__init__.py`, `src/apprc/cli/_facade.py`, `src/apprc/interfaces/__init__.py`, `src/apprc/interfaces/_facade.py`
- **Observed while:** implementing and auditing lazy TUI exports for optional Textual support
- **Why not fixed now:** the current implementation is tested and type-checks; removing duplication needs a focused facade typing design rather than a quick release change
- **Evidence:** runtime export lists live in each `_facade.py`, while matching `TYPE_CHECKING` imports in each `__init__.py` keep Pyright aware of lazy attributes. A missed addition or removal can drift between runtime `__all__` and the static type surface.
- **Context:** Lazy facades are now important for keeping optional dependencies optional, but manually mirroring public names makes future public API changes easier to get half-right.
- **Suggested next step:** Introduce a drift-proof lazy facade typing pattern, generated `.pyi` files included in source, or tests that compare facade `__all__` against the static export declarations.
