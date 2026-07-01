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
>       - **Question**: Design, behavior, or ownership uncertainty needing investigation.
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
> - **Area:** `path/or/symbol`
> - **Observed while:** short context
> - **Evidence:** concrete observation
> - **Why not fixed now:** scope, risk, uncertainty, or user decision needed
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
2. [2026-07-01](#2026-07-01)
   1. [P2 / E1 \[Question\] - *Host CLI runtime API names describe the mechanism*](#p2--e1-question---host-cli-runtime-api-names-describe-the-mechanism)
   2. [P2 / E1 \[Code smell\] - *Host CLI option preservation loses host-only values*](#p2--e1-code-smell---host-cli-option-preservation-loses-host-only-values)
   3. [P2 / E2 \[Code smell\] - *Default CLI state is awkward to subclass*](#p2--e2-code-smell---default-cli-state-is-awkward-to-subclass)
   4. [P3 / E1 \[Code smell\] - *Lazy aggregate facades hide import cycles*](#p3--e1-code-smell---lazy-aggregate-facades-hide-import-cycles)
   5. [P3 / E2 \[Code smell\] - *Root facade needs a public-surface snapshot*](#p3--e2-code-smell---root-facade-needs-a-public-surface-snapshot)
   6. [P3 / E1 \[Code smell\] - *TUI internals still need workflow-level splits*](#p3--e1-code-smell---tui-internals-still-need-workflow-level-splits)
   7. [P3 / E2 \[Code smell\] - *Config command base module still owns broad cross-command state*](#p3--e2-code-smell---config-command-base-module-still-owns-broad-cross-command-state)
   8. [P3 / E1 \[Code smell\] - *Host CLI forwarding still needs local glue*](#p3--e1-code-smell---host-cli-forwarding-still-needs-local-glue)
   9. [P3 / E2 \[Question\] - *Dev-only example kit registry may need a public helper*](#p3--e2-question---dev-only-example-kit-registry-may-need-a-public-helper)
   10. [P3 / E1 \[Question\] - *Diagnostics payload shape may need a typed model*](#p3--e1-question---diagnostics-payload-shape-may-need-a-typed-model)
   11. [P3 / E3 \[Code smell\] - *Runtime-config test names still reflect removed packages*](#p3--e3-code-smell---runtime-config-test-names-still-reflect-removed-packages)

<br>

---

<br>

# 2026-07-01

## P2 / E1 [Question] - *Host CLI runtime API names describe the mechanism*
- **Area:** [0.17.0] `apprc.ConfigCliBridge`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** `ConfigCliBridge`, `ConfigCliSession`,
  `HostCliBootstrapPolicy`, and `BootstraplessCommand` describe bridge and
  bootstrap mechanics, while the actual concept is a host CLI runtime
  coordinator that decides when AppRC runtime bootstrap is needed and builds
  app-owned state.
- **Why not fixed now:** Public naming changes would broaden the API impact of
  the architecture rewrite and need a focused decision before release.
- **Suggested next step:** Decide whether to rename the API before publishing
  it, for example `ConfigCliBridge` -> `HostCliRuntime`,
  `ConfigCliSession` -> `HostCliSession`, `HostCliBootstrapPolicy` ->
  `HostCliRuntimePolicy`, `BootstraplessCommand` -> `RuntimeFreeCommand`, and
  `bootstrap_policy=` -> `runtime_policy=`. Related:
  [host option preservation](#p2--e1-code-smell---host-cli-option-preservation-loses-host-only-values)
  and
  [host CLI forwarding](#p3--e1-code-smell---host-cli-forwarding-still-needs-local-glue).

## P2 / E1 [Code smell] - *Host CLI option preservation loses host-only values*
- **Area:** [0.17.0] `apprc.CliBootstrapContext`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** `ConfigCliBridge.prepare()` receives a generic host option
  object, but `CliBootstrapContext` stores only the normalized AppRC
  `CliBootstrapOptions`. App-specific options reach `state_factory`, but
  skipped-runtime-bootstrap paths lose those host-only values unless the
  application stores them separately.
- **Why not fixed now:** Preserving the original host option object changes
  context shape and typing, and needs a dedicated API pass.
- **Suggested next step:** Make `CliBootstrapContext` preserve both
  `bootstrap_options: CliBootstrapOptions` and `host_options: OptionsT`, then
  add a typed reader such as `host_options_from(ctx, expected_type)`. Related:
  [host runtime naming](#p2--e1-question---host-cli-runtime-api-names-describe-the-mechanism)
  and
  [host CLI forwarding](#p3--e1-code-smell---host-cli-forwarding-still-needs-local-glue).

## P2 / E2 [Code smell] - *Default CLI state is awkward to subclass*
- **Area:** [0.17.0] `apprc.DefaultConfigCliState`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** Application CLI state often wants to inherit from
  `DefaultConfigCliState` and add required runtime fields, but regular dataclass
  field ordering is awkward when the base class has default-valued fields.
- **Why not fixed now:** Changing the dataclass declaration affects generated
  config command state construction and example app typing.
- **Suggested next step:** Make `DefaultConfigCliState` subclass-friendly,
  likely with `@dataclass(slots=True, kw_only=True)`, then update examples and
  docs to subclass it where app-owned CLI state is exposed to generated config
  commands.

## P3 / E1 [Code smell] - *Lazy aggregate facades hide import cycles*
- **Area:** [0.17.0] `src/apprc/runtime/_facade.py`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** `apprc.runtime`, `apprc.user_files`, and
  `apprc.user_files.storage_roots` still use the shared lazy facade helper
  because eager imports created cycles around `EnvConfig`, `AppConfigSpec`, and
  storage loading.
- **Why not fixed now:** Removing the lazy facades requires untangling import
  cycles across runtime, user file, and storage boundaries.
- **Suggested next step:** Reduce the import cycles enough that aggregate
  package facades can become plain import-only `__init__.py` files.

## P3 / E2 [Code smell] - *Root facade needs a public-surface snapshot*
- **Area:** [0.17.0] `src/apprc/__init__.py`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** The root facade is intentionally large because the integration
  rule is `import apprc` followed by `apprc.<name>`. It now exports config
  definition, runtime bootstrap, diagnostics, CLI/TUI hooks, dotenv helpers,
  storage helpers, provenance helpers, and utility helpers.
- **Why not fixed now:** The large facade is intentional, but its stability
  needs a targeted public API guard rather than more refactoring.
- **Suggested next step:** Add a generated public-surface snapshot test so the
  facade stays explicit without becoming surprising.

## P3 / E1 [Code smell] - *TUI internals still need workflow-level splits*
- **Area:** [0.17.0] `src/apprc/interfaces/tui`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** The TUI files moved into `apprc.interfaces.tui`, but editor,
  modal, and workflow internals remain behavior-preserving moves. Some modules
  are still large.
- **Why not fixed now:** Splitting TUI internals further needs more UI-state
  regression coverage before changing the shape.
- **Suggested next step:** Add focused TUI interaction tests, then split editor
  workflows by user action.

## P3 / E2 [Code smell] - *Config command base module still owns broad cross-command state*
- **Area:** [0.17.0] `src/apprc/interfaces/cli/config_command/_base.py`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** The generated config command handler was split into runtime,
  storage, app-wide, editor, and selector-context modules, but `_base.py` still
  owns cross-command Typer context recovery, selector resolution, and runtime
  payload handling.
- **Why not fixed now:** Extracting more pieces safely needs focused tests
  around selector context fallback and bootstrapless command state.
- **Suggested next step:** Add those tests first, then extract narrower helpers
  from `_base.py`.

## P3 / E1 [Code smell] - *Host CLI forwarding still needs local glue*
- **Area:** [0.17.0] `apprc.apprc_options_to_args`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** AppRC exposes `args_provider`, `apprc_options_to_args()`, and
  `run_typer_app()`, but nested in-process CLIs still need local glue when the
  parent command constructs child argv and the child runtime policy must
  inspect those forwarded tokens.
- **Why not fixed now:** The right helper boundary depends on the host CLI
  runtime API and option-preservation decisions.
- **Suggested next step:** Add a small forwarding helper around the runtime
  coordinator, such as `runtime.forwarded_args(args)` or
  `runtime.run_forwarded(...)`, while keeping domain-specific option
  serialization in applications. Related:
  [host runtime naming](#p2--e1-question---host-cli-runtime-api-names-describe-the-mechanism)
  and
  [host option preservation](#p2--e1-code-smell---host-cli-option-preservation-loses-host-only-values).

## P3 / E2 [Question] - *Dev-only example kit registry may need a public helper*
- **Area:** [0.17.0] `examples/example_apps`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** Runnable examples now live in one dev-only distribution with
  separate app packages for each AppRC mode. The bootstrap helper dynamically
  imports their `config.KIT` objects so downstream repositories that type-check
  only `../apprc/src` do not need `../apprc/examples/example_apps/src` on their
  static type path.
- **Why not fixed now:** Exposing a helper API for examples would add another
  public-ish surface to dev tooling before usage pressure is clear.
- **Suggested next step:** If examples grow beyond smoke coverage, add a tiny
  `apprc-example-apps` helper API that exposes the example kit registry
  directly, while keeping it outside the production `apprc` package.

## P3 / E1 [Question] - *Diagnostics payload shape may need a typed model*
- **Area:** [0.17.0] `apprc.ConfigDoctorPayload`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** Diagnostics now separate `payload.py`, `messages.py`, and
  `_diagnosis.py`, but `ConfigDoctorPayload` remains a large `TypedDict`
  because CLI JSON output, tests, and downstream tooling expect the current
  shape.
- **Why not fixed now:** A dataclass model would require deciding whether the
  current JSON keys are locked as public API.
- **Suggested next step:** Decide whether the JSON payload is stable public API,
  then consider a dataclass model with an explicit `.to_payload()` method.

## P3 / E3 [Code smell] - *Runtime-config test names still reflect removed packages*
- **Area:** [0.17.0] `tests`
- **Observed while:** 0.17.0 package architecture rewrite
- **Evidence:** Some AppRC test filenames still contain `runtime_config`
  because they now assert the removal of the old package.
- **Why not fixed now:** Renaming these tests during the architecture move would
  add noisy file churn without changing behavior.
- **Suggested next step:** Rename those tests to architecture-oriented names
  once the breaking rewrite settles.
