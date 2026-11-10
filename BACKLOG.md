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
   1. [P2 / E1 \[Code smell\] - *Legacy replacement recovery has an implicit filename schema*](#p2--e1-code-smell---legacy-replacement-recovery-has-an-implicit-filename-schema)
   1. [P3 / E1 \[Code smell\] - *Saved management code doubles as installation configuration*](#p3--e1-code-smell---saved-management-code-doubles-as-installation-configuration)
   1. [P3 / E2 \[Code smell\] - *Config instances maintain overlapping provenance stores*](#p3--e2-code-smell---config-instances-maintain-overlapping-provenance-stores)
   1. [P3 / E2 \[Code smell\] - *Unused dotenv editing APIs duplicate the manager workflow*](#p3--e2-code-smell---unused-dotenv-editing-apis-duplicate-the-manager-workflow)
3. [2026-11-09](#2026-11-09)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)
4. [2026-09-04](#2026-09-04)
   1. [P3 / E1 \[Code smell\] - *Multi-file updates can stop between replacements*](#p3--e1-code-smell---multi-file-updates-can-stop-between-replacements)
   1. [P3 / E1 \[Code smell\] - *Workspace presentation state has multiple owners*](#p3--e1-code-smell---workspace-presentation-state-has-multiple-owners)
5. [2026-07-14](#2026-07-14)
   1. [P3 / E3 \[Tooling\] - *Removed-module tests are sensitive to namespace-only remnants*](#p3--e3-tooling---removed-module-tests-are-sensitive-to-namespace-only-remnants)


<br>

# 2026-11-10

Reviewed AppRC `0.32.0` at `aaeefe`. These findings concern maintenance and relearning cost, not confirmed runtime failures. Follow-up work must preserve independent optional capabilities and the existing ownership, revision, permission, and recovery guarantees.

## P2 / E1 [Code smell] - *Legacy replacement recovery has an implicit filename schema*
- **Area:** `src/apprc/definition/installation.py`, `src/apprc/distribution/runtime/legacy_replacement.py`
- **Observed while:** Reviewing the post-release installation state model.
- **Why not fixed now:** Changing durable recovery records requires a focused implementation and migration decision; this request is analysis-only.
- **Evidence:** [`InstallationOperation`](src/apprc/definition/installation.py#L390-L404) has no explicit pre-migration legacy-replacement variant. [`legacy_replacement.py`](src/apprc/distribution/runtime/legacy_replacement.py#L948-L974) stores controller files, receipt/RECORD proof, and retained acquisition/support inputs together in `CleanupInventory.retained`. [`is_pending_legacy_replacement()`](src/apprc/distribution/runtime/legacy_replacement.py#L160-L190) identifies the state from filenames; [`_load_pending_inputs()`](src/apprc/distribution/runtime/legacy_replacement.py#L791-L843) decodes `support-<hex>` names and distinguishes `acquisition-*` entries.
- **Context:** Retaining those bytes is necessary for recovery after the original source disappears. The problem is a second durable schema hidden inside a cleanup collection: file naming, operation detection, reconstruction, and cleanup must change together, although the typed record does not express their relationship.
- **Suggested next step:** Give pending legacy replacement explicit typed recovery evidence for receipt/controller proof, installed RECORD identity, acquisition input, and support-input mappings. Stop inferring evidence roles from filenames while retaining digest and containment checks. Coordinate support-input ownership with [saved management configuration](#p3--e1-code-smell---saved-management-code-doubles-as-installation-configuration); do not introduce another installation authority.

## P3 / E1 [Code smell] - *Saved management code doubles as installation configuration*
- **Area:** `src/apprc/distribution/rendering.py`, `src/apprc/distribution/runtime/installation.py`, `src/apprc/distribution/runtime/launcher.py`, `src/apprc/distribution/standalone.py`
- **Observed while:** Following generated launch/uninstall support into runtime binding.
- **Why not fixed now:** This changes the saved-support format and bootstrap boundary, not just presentation or naming.
- **Evidence:** [`_launcher_script()` and `_uninstaller_script()`](src/apprc/distribution/rendering.py#L436-L634) embed executable management policy in strings. [`bind_install_support()`](src/apprc/distribution/runtime/installation.py#L826-L859) recovers the interpreter by scanning saved Python for `BASE_PYTHON = `, then [binds new output](src/apprc/distribution/runtime/installation.py#L885-L891) by replacing an exact quoted placeholder. [`runtime/launcher.py`](src/apprc/distribution/runtime/launcher.py) implements another launcher, but is absent from the [standalone closure](src/apprc/distribution/standalone.py#L14-L44); repository searches found no caller outside its own entry point.
- **Context:** Executable syntax is also a data protocol, so a harmless-looking rendering change can require changes in runtime binding. The apparently natural launcher module is not the shipped implementation. The stdlib-only bootstrap boundary is justified; hiding that boundary inside generated strings is not required by it.
- **Suggested next step:** Use canonical stdlib-only source files for saved management programs, following the existing `namespace_finalizer.py` approach. Keep interpreter settings as explicit owned, digest-covered support data rather than parsing Python source. Adopt or remove the unused launcher so one implementation remains. Preserve interpreter validation, saved backend selection, and previews that do not provision anything. Coordinate retained support inputs with [legacy replacement recovery](#p2--e1-code-smell---legacy-replacement-recovery-has-an-implicit-filename-schema).

## P3 / E2 [Code smell] - *Config instances maintain overlapping provenance stores*
- **Area:** `src/apprc/runtime/config/{base,config,_origins}.py`, `src/apprc/runtime/provenance/python.py`
- **Observed while:** Following constructor, assignment, provenance inspection, and reload behavior.
- **Why not fixed now:** Consolidation must preserve constructor protection, Python-only fields, owner metadata, and existing provenance behavior.
- **Evidence:** [`BaseConfig`](src/apprc/runtime/config/base.py#L52-L80) initializes `_apprc_provenance_origins`; [`Config`](src/apprc/runtime/config/config.py#L95-L100) adds `_apprc_field_origins` and [captures constructor fields again](src/apprc/runtime/config/config.py#L150-L173). [Assignment](src/apprc/runtime/config/config.py#L460-L483) first updates the base store and then the owner-backed store. [Provenance reads](src/apprc/runtime/config/config.py#L347-L377) choose between them, while [reload protection](src/apprc/runtime/config/config.py#L289-L299) consults the latter.
- **Context:** Owner-backed fields participate in two instance maps keyed by the same Python field names and holding the same origin-state type. Maintainers must know which map each lifecycle operation treats as authoritative. Different metadata/default origins for Python-only and environment-backed fields are legitimate, but do not inherently require overlapping storage.
- **Suggested next step:** Use one instance provenance map and one update helper, with `Config` enriching records with owner/environment metadata. Completion means construction, assignment, scoped overrides, binding, inspection, and reload use that store without changing public origin reporting or override protection.

## P3 / E2 [Code smell] - *Unused dotenv editing APIs duplicate the manager workflow*
- **Area:** `src/apprc/user_files/env_files/updates.py`, `src/apprc/user_files/env_files/__init__.py`, `tests/test_env_file.py`
- **Observed while:** Tracing maintained callers of settings-editing entry points.
- **Why not fixed now:** Removal must move meaningful behavior coverage onto maintained primitives; this request does not authorize code deletion.
- **Evidence:** [`updates.py`](src/apprc/user_files/env_files/updates.py#L84-L174) retains `set_workspace_dotenv_value`, `set_env_file_value`, and `plan_workspace_dotenv_value_update`, plus [two clear wrappers](src/apprc/user_files/env_files/updates.py#L248-L306). Searches across production, packaging, examples, and tests found calls only inside those wrappers and `tests/test_env_file.py`. Maintained CLI/TUI/Gradio consumers instead use [`ConfigManager` planning/application](src/apprc/services/manager.py#L293-L415); supported-facade tests exclude the old helpers.
- **Context:** The internal package still presents a second complete editing workflow with its own workspace validation and exception translation. Relearning settings writes requires separating live orchestration from a convenience route retained by tests. Its low-level document-preservation tests are meaningful and must not simply be discarded.
- **Suggested next step:** Remove the five unused wrappers and their aggregate re-exports. Keep the plan/apply primitives used by `ConfigManager`, move parsing/newline/duplicate-assignment/zero-write assertions onto those primitives, and keep application policy in manager tests. Preserve the same manager boundary when simplifying [workspace presentation ownership](#p3--e1-code-smell---workspace-presentation-state-has-multiple-owners).

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

# 2026-09-04


## P3 / E1 [Code smell] - *Multi-file updates can stop between replacements*
- **Area:** `src/apprc/user_files/env_files/secret_migration.py`, `src/apprc/user_files/app_home/{writes,locations}.py`, `src/apprc/services/manager.py`
- **Observed while:** Implementing explicit resolution/shared management; rechecked against the post-`0.32.0` source.
- **Why not fixed now:** Locks and revision checks serialize managed writes, but do not make two replacements crash-atomic. Recovery-policy changes are outside this backlog review.
- **Evidence:** [`apply_secret_migration()`](src/apprc/user_files/env_files/secret_migration.py#L105-L129) checks both revisions under the managed lock, writes the private companion, then replaces the ordinary dotenv. Each replacement is atomic individually. An interruption between them can leave both assignments; the private copy wins within that layer.
- **Context:** The limitation is still current, but saying there is no recovery protocol was too broad: migration can be replanned after interruption. Replaying the original plan fails its revision check. Existing successful-migration and write-lock coverage does not inject failure between these two replacements.
- **Suggested next step:** Preserve the value-first ordering. Add focused failure-between-writes coverage in the existing suite and document fresh-plan recovery before considering more machinery. Introduce a recovery journal only if automatic crash recovery becomes a requirement; do not treat writer locking as a two-file transaction.


<a id="p3--e1-code-smell---cli-and-editor-composition-remain-monolithic"></a>

## P3 / E1 [Code smell] - *Workspace presentation state has multiple owners*
- **Area:** `src/apprc/interfaces/tui/editor/{app,workspace_base,workspace_editing,setup}.py`
- **Observed while:** Originally moving loading/persistence into shared operations; revisited in the post-`0.32.0` maintainability review.
- **Why not fixed now:** The remaining problem is presentation-state ownership, not persistence. Changing workspace interaction is outside this analysis-only request.
- **Evidence:** [`WorkspaceWorkflowBase`](src/apprc/interfaces/tui/editor/workspace_base.py#L12-L31) retains the concrete `ConfigEditorScreen`. [Editing workflows](src/apprc/interfaces/tui/editor/workspace_editing.py#L94-L103) assign its registry and call private refresh methods; the screen's [outer action runner](src/apprc/interfaces/tui/editor/app.py#L431-L446) refreshes again after workflows complete. The screen also owns selection restoration and button availability. `ConfigEditorApp` is now a thin host, and CLI handlers already delegate execution; nested Typer declarations alone are not a separate finding.
- **Context:** The screen → workflow → screen cycle moves methods into other files without giving workspace state one owner. A maintainer must trace both layers to understand registry replacement, selection, and refresh ordering. Persistence already belongs to `ConfigManager`/`WorkspaceManager` and should stay there.
- **Suggested next step:** Give workspace-pane state, selection, list refresh, and button availability one presentation owner. Let operations report results and desired selection instead of accepting the whole screen and mutating private state. Completion means one post-operation refresh boundary, without a generic UI framework. Keep shared manager editing rather than the [unused direct dotenv workflow](#p3--e2-code-smell---unused-dotenv-editing-apis-duplicate-the-manager-workflow).


<br>

# 2026-07-14

<a id="p3--e3-tooling---stale-bytecode-recreates-removed-package-namespaces"></a>

## P3 / E3 [Tooling] - *Removed-module tests are sensitive to namespace-only remnants*
- **Area:** `tests/test_architecture_public_api.py` (`test_old_runtime_config_package_is_removed`, `test_logging_package_is_removed`)
- **Observed while:** Historical post-migration test failures; rechecked the current removal assertions after `0.32.0`.
- **Why not fixed now:** No active failure is observed in the current checkout. The remaining question is the intended removal-test contract, not a production repair or a request to delete local files.
- **Evidence:** [The package-level removal tests](tests/test_architecture_public_api.py#L128-L140) still require `ModuleNotFoundError`. Namespace-only directories can make those package imports succeed even without legacy Python source. The historically implicated `src/apprc/runtime_config` and `src/apprc/logging` directories are absent from the current checkout, so their old failure must not be presented as current.
- **Context:** Ignored bytecode is local development state, not retained production implementation. The separately observed `src/apprc/user_files/storage_roots/__pycache__` likewise does not establish a failure of these tests or a runtime defect.
- **Suggested next step:** Clarify whether the guards require complete import-path absence or only removal of legacy APIs. If namespace-only remnants are acceptable, test API removal without rejecting them; otherwise document targeted developer-cache cleanup. No global cache deletion or new verification infrastructure is needed.

<br>
