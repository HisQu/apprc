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
2. [2026-07-14](#2026-07-14)
3. [2026-07-03](#2026-07-03)


<br>

# 2026-07-14

## P2 / E1 [Question] - *Define strict and convenience runtime configuration modes*
- **Area:** `src/apprc/public/app_rc.py`, `src/apprc/public/config.py`, `src/apprc/runtime/bootstrap.py`
- **Observed while:** Tracing how haiu, OPA, and datamodel-workflow construct runtime configuration during ontology-workspace operations.
- **Why not fixed now:** This needs an AppRC API and compatibility design pass; the current task is to capture the cross-repository issue, not change AppRC behavior opportunistically.
- **Evidence:** AppRC documents that applications should call `bootstrap()` before constructing runtime config, but direct config construction remains valid and falls back to Python field defaults when bootstrap was omitted. Downstream code therefore cannot distinguish an intentionally standalone config from a runtime config that skipped bootstrap.
- **Context:** AppRC should support two deliberate modes: an explicit application mode that bootstraps once and passes resolved config objects through runtime, and a future library-like convenience mode that may ensure bootstrap at a high-level client boundary. Preserve the current low-level constructor behavior for tests and standalone use. Do not put hidden bootstrap in `ConfigBase`, raw config constructors, or downstream workspace constructors, and do not require a process-wide config singleton; resolved config objects must remain passable dependencies.
- **Suggested next step:** Design an additive runtime-resolution API or validation marker that applications and libraries can require after bootstrap. It should reject required fields whose origin is a Python fallback, expose bootstrap/resolution state clearly, and define idempotent behavior for repeated bootstrap calls plus an error for conflicting calls. If an auto-bootstrap convenience API is added, make its scope and policy explicit, ensure it bootstraps at most once per process, and keep it separate from low-level config construction. Add tests showing that existing direct construction remains compatible, strict runtime construction fails before bootstrap, explicit bootstrap succeeds, and convenience clients do not re-bootstrap during nested runtime operations.

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
