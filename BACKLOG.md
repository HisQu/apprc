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
2. [2026-11-22](#2026-11-22)
   1. [CSC-14 · Preserve inherited slots on mixed-layout config classes](#csc-14)
   2. [CSC-15 · Bind Gradio display and edits to one workspace](#csc-15)
   3. [CSC-16 · Give command publication and recovery one owner](#csc-16)
   4. [CSC-17 · Align uv workspace pattern discovery across lifecycle routes](#csc-17)
   5. [CSC-18 · Move installation diagnostic formatting out of command registration](#csc-18)
   6. [CSC-19 · Give native lifecycle test failures a narrower scope](#csc-19)
   7. [CSC-20 · Avoid repeated field lookups during settings inspection and binding](#csc-20)
   8. [CSC-21 · Prune project metadata walks at generated directories](#csc-21)
   9. [CSC-22 · Correct the Gradio editor constructor in Explanations](#csc-22)
   10. [CSC-23 · Print editable update retry commands on their own lines](#csc-23)
   11. [CSC-24 · Describe workspace reconnect file creation before confirmation](#csc-24)
   12. [CSC-25 · Retire the unused missing-archive prune operation](#csc-25)
   13. [CSC-26 · Recheck workspace records after acquiring locks](#csc-26)
   14. [CSC-27 · Make private companion failures consistent with workspace commit status](#csc-27)
   15. [CSC-28 · Address the multithreaded fork warning in coordination tests](#csc-28)
3. [2026-11-09](#2026-11-09)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)


<br>

# 2026-11-22

**Goal.** Review AppRC for defects and maintainability problems, including
deeper edge cases, and leave actionable work here for follow-up.

**Specifics.** Reviewed `main` at `b1b5e03` (tree `1d6745`) on Linux with Python
3.14.2. The scan followed configuration declaration, resolution and writes,
workspace lifecycle, CLI diagnostics and help, Textual and Gradio workflows,
managed and editable installation, update, uninstall, and source packaging. It
compared adjacent tests and docs and checked prior CSC dispositions before
adding findings. The entries are ordered by the CSC checklist. Finding IDs
continue the [previous report](code-smells.md).

Local verification passed 1,204 core tests with 40 skips, nine GUI tests
including the single-client browser workflow, and all eight example smoke runs.
Ruff lint and formatting passed. Pyright found zero errors and five warnings
for Windows-specific imports on Linux. The workspace and configuration edge
cases below have source evidence and pending targeted regressions. The install
and uninstall review checked checkpoint order,
publication and cleanup ownership, and the handoff between launchers and
helpers. Those steps rely on ordered mutations. No independent runtime job or
mutable-filesystem cache justified a proposal. The class-level caches use
immutable schema or slot metadata and carry the process-lifetime trade-off
described in the previous report. Native Windows and macOS, opt-in native builds,
and a multi-client Gradio regression remain outside the verification for this
scan. Follow-ups preserve public contracts unless an entry identifies a specific
behavior or compatibility decision.

<a id="csc-14"></a>

## P2 / E2 [Bug risk] - *Preserve inherited slots on mixed-layout config classes*

- **Area:** `ConfigBase` mutation tracking and shared state transfer.
- **Observed while:** Tracing assignment, copy, and scoped overrides through the SDK.
- **Why not fixed now:** The fix needs a regression across the supported config layouts.
- **Evidence:** `has_instance_attr()` returns from the dictionary lookup whenever an instance has a `__dict__`. A dictionary-backed subclass can still inherit slots from a slotted base. Those values pass through the assignment path for new attributes, skipping the existing-field hooks. The copy path checks both storage locations, but reads literal `__slots__` names, which can miss manually declared double-underscore slots. [State transfer](src/apprc/runtime/config/_state_transfer.py#L32) · [Assignment hooks](src/apprc/runtime/config/base.py#L118) · [Existing copy cases](tests/test_base_config.py#L206)
- **Context:** The public config lifecycle promises mutation tracking and state-preserving copies. A mixed-layout inheritance tree can therefore behave differently depending on which class declared the field.
- **Suggested next step:** Test reassignment, provenance, and shallow and deep copies with a dictionary-backed subclass of a slotted config and with a manually named private slot. Use the same slot inventory in assignment and copy while preserving quiet initial assignment and constructor-free copies.

<a id="csc-15"></a>

## P2 / E2 [Bug risk] - *Bind Gradio display and edits to one workspace*

- **Area:** `apprc_gui.ConfigEditor` dynamic render and workspace callbacks.
- **Observed while:** Following a browser selection through field inspection, rendering, and save.
- **Why not fixed now:** The follow-up needs to define how an editor view tracks the persisted workspace selection.
- **Evidence:** Gradio stores the revision in `gr.State` and stores the selector on the editor instance. A render inspects with that attribute, then workspace rendering may initialize it from the registry. Field callbacks read the attribute again instead of using the workspace already carried by `ConfigSectionContext`. The selection callbacks also update that shared attribute. [Render](src/apprc_dev/packaging/gui/src/apprc_gui/view.py#L73) · [Registry selection](src/apprc_dev/packaging/gui/src/apprc_gui/view.py#L167) · [Field callbacks](src/apprc_dev/packaging/gui/src/apprc_gui/view.py#L293) · [Browser case](src/apprc_dev/packaging/gui/tests/test_browser_interactivity.py#L73)
- **Context:** A change between inspection and callback construction can make a displayed value and its Save button refer to different workspaces. The browser case exercises one page and a sequential selection. The documented host construction shares one editor instance for a `Blocks` app. [Host example](docs/How-To-User-Guides.md#add-a-gradio-settings-page)
- **Suggested next step:** Capture the workspace for the entire render and pass that capture through the built-in field and secret actions. Verify an external registry change and two browser sessions. Keep the explicit command to persist the application default. Decide how an open view should refresh that default separately from the write-target guarantee.

<a id="csc-16"></a>

## P3 / E1 [Code smell] - *Give command publication and recovery one owner*

- **Area:** `apprc.distribution.runtime.installation` command publication.
- **Observed while:** Following command bytes or link targets from preparation through rollback and post-activation cleanup.
- **Why not fixed now:** Moving the boundary needs coverage for managed and editable publication, repair, and resumed operations.
- **Evidence:** The lifecycle module also implements command addressing, before-image persistence, intended-image rebuilding, publication, restoration, and cleanup. Managed and editable call sites separately interpret publication outputs and merge owned output lists. Both already share the activation commit, so extracting activation again would leave the publication concern in the same places. [Publication preparation](src/apprc/distribution/runtime/installation.py#L317) · [Resume](src/apprc/distribution/runtime/installation.py#L416) · [Restore](src/apprc/distribution/runtime/installation.py#L518) · [Managed caller](src/apprc/distribution/runtime/installation.py#L1403) · [Editable caller](src/apprc/distribution/runtime/installation.py#L2415)
- **Context:** A change to command ownership or bytes currently crosses image handling, durable state, and route-specific publication loops. The operation order remains visible in the lifecycle orchestrator.
- **Suggested next step:** Move the publication mechanics behind one private boundary, using the existing `PublicationImage` and `PublicationOutput`. Keep the recorded formats, revision checks, lock boundaries, ordering, and post-commit warning behavior. Exercise failures before and after publication with the existing rollback and Windows version fixtures. [Installation rollback tests](tests/test_installation_rollback.py)

<a id="csc-17"></a>

## P3 / E2 [Code smell] - *Align uv workspace pattern discovery across lifecycle routes*

- **Area:** Editable environment discovery and source snapshot validation.
- **Observed while:** Comparing the same `tool.uv.workspace` declarations at registration and package-build entry points.
- **Why not fixed now:** A shared parser must preserve the different purposes of those checks and the lightweight registration import boundary.
- **Evidence:** Both paths validate `members` and `exclude`, reject unsafe pattern spellings, expand globs, and check containment independently. Editable discovery uses `root_dir` and `include_hidden=True` and checks against the active workspace root. Snapshot validation uses a prefixed glob with the hidden default and checks against the exported tree. It additionally requires committed member metadata. [Editable discovery](src/apprc/definition/resolution.py#L21) · [Snapshot validation](src/apprc/distribution/project.py#L67)
- **Context:** A change in accepted pattern syntax can affect one lifecycle route while leaving the other behind. The observed glob differences are source facts. Acceptance for individual hidden or nested patterns needs fixtures before changing either route.
- **Suggested next step:** Establish shared pattern parsing and expansion with tests for nested members, exclusions, hidden entries, and unmatched patterns. Keep route-specific containment, physical identity, and committed-member checks with their callers. Compare the current accepted cases first and document any deliberate compatibility change. [Source identity tests](tests/test_installation_source_identity.py) · [Snapshot tests](tests/test_project_snapshot.py)

<a id="csc-18"></a>

## P3 / E2 [Code smell] - *Move installation diagnostic formatting out of command registration*

- **Area:** Mounted installation commands and `app doctor` output.
- **Observed while:** Tracing one `InstallationInspection` into CLI JSON.
- **Why not fixed now:** Several human and machine output routes consume the inspection, including install preparation and migration.
- **Evidence:** The doctor builder imports `_inspection_payload` from the command registration module, then constructs the same diagnostic dictionaries a second time for checks and output. The formatter also sits next to the registration callbacks and unrelated migration and uninstall handlers. [Doctor aggregation](src/apprc/interfaces/cli/diagnostics/application.py#L244) · [Inspection formatter](src/apprc/interfaces/cli/installation_command.py#L1122) · [Preparation consumer](src/apprc/interfaces/cli/installation_command.py#L1218)
- **Context:** Contributors tracing a payload field have to cross command registration. Explicit shape matters because raw installation records carry more information than the mounted summary.
- **Suggested next step:** Put the mounted inspection and diagnostic projections with existing CLI output code and reuse them in the doctor builder. Preserve nested JSON keys and values, and keep output imports lazy where required. Check existing machine-output cases and fresh-process help. [Installation output](src/apprc/interfaces/cli/_installation_output.py) · [Doctor tests](tests/test_cli_doctor_installation.py)

<a id="csc-19"></a>

## P3 / E2 [Tooling] - *Give native lifecycle test failures a narrower scope*

- **Area:** Native Linux PyApp lifecycle tests.
- **Observed while:** Locating coverage for managed activation, bridge diagnostics, update, and editable registration.
- **Why not fixed now:** Reusing built products while separating test state requires a native test run.
- **Evidence:** One parametrized test spans more than 600 lines, starting with artifact validation and a fresh install, then exercising diagnostics, repair, leased runtime retirement, managed cleanup and editable registration and unregistration. Both temporary-path variants run all phases, and a failure early in a run prevents the later contracts from being tested. [Start of scenario](tests/test_distribution_pyapp.py#L159) · [Retirement and cleanup](tests/test_distribution_pyapp.py#L527) · [Editable cleanup](tests/test_distribution_pyapp.py#L733)
- **Context:** Some assertions need a cumulative lifecycle, especially lease release and cleanup retry. Other contracts need only prepared products and isolated installs. The suite already has reusable native build support. [Native test support](tests/support_pyapp.py)
- **Suggested next step:** Keep a composed lifecycle smoke case, and give independent contracts separately selectable tests that reuse the existing built-product fixture. Keep the linked-temporary-parent variant where the path differs materially. Compare collected scenario coverage and run the opt-in native suite before removing overlapping assertions.

<a id="csc-20"></a>

## P3 / E2 [Code smell] - *Avoid repeated field lookups during settings inspection and binding*

- **Area:** `ConfigOwner.env_key()`, field inspection, and runtime settings binding.
- **Observed while:** Following a settings section through doctor, editors, and runtime construction.
- **Why not fixed now:** The benefit depends on owner sizes and needs measurement alongside conversion and validation costs.
- **Evidence:** `ConfigOwner.env_key()` looks up the name by walking the fields. Inspection, supplied-field selection, serialization, and binding call it while already iterating those same field objects. The lookup portion scales quadratically in the number of fields per owner. Inspection also converts individually to retain per-field errors. [Owner lookup](src/apprc/definition/env_config/schema.py#L110) · [Inspection](src/apprc/services/inspection.py#L66) · [Loading](src/apprc/runtime/config/_loading.py#L48) · [Binding](src/apprc/runtime/config/_binding.py#L141)
- **Context:** The owner schema already carries the prefix and each field's suffix. Reusing those known inputs can make traversal linear without keeping mutable settings in a cache. Inspection still needs to report multiple independent failures in one result.
- **Suggested next step:** Benchmark a large owner and remove redundant name resolution at call sites that already have the field. Preserve name lookup for consumers that have only a name, and verify prefixes, imported aliases, and per-field conversion errors. Record the measured gain before adding any persistent index.

<a id="csc-21"></a>

## P3 / E2 [Code smell] - *Prune project metadata walks at generated directories*

- **Area:** Source snapshot project metadata and lockfile checks.
- **Observed while:** Following authoring from the committed source tree through preparation and archive assembly.
- **Why not fixed now:** The metadata exclusions differ deliberately from output cleanup and need baseline tests before consolidation.
- **Evidence:** `_project_configuration()` and `_project_lockfiles()` maintain identical exclusion sets and start separate recursive walks before filtering paths beneath those directories. The build calls each scan both before and after preparation. The generated-output cleanup uses related names, with separate rules for preserving tracked output. [Metadata scans](src/apprc/distribution/project.py#L263) · [Before and after checks](src/apprc/distribution/project.py#L408) · [Cleanup policy](src/apprc/distribution/project.py#L174)
- **Context:** One walk per snapshot phase could skip excluded subtrees and capture both inventories. This addresses repeated directory traversal and policy duplication. The previous memory measurement concerned archive assembly and remains applicable to that distinct question. [Prior measurement](code-smells.md#csc-05)
- **Suggested next step:** Use one metadata walk with pruning. Retain separate reporting for changed project config and lockfiles and keep the tracked-output retention rules. Run snapshot tests and measure directory visits on a large tree before pursuing further optimization.

<a id="csc-22"></a>

## P3 / E3 [Docs drift] - *Correct the Gradio editor constructor in Explanations*

- **Area:** Gradio editor explanation and host API.
- **Observed while:** Comparing browser setup instructions with the installed editor class.
- **Why not fixed now:** This pass records the mismatch for a documentation fix.
- **Evidence:** Explanations shows `ConfigEditor(manager, *, workspaces=None)`. The implementation accepts `workspace_manager` and makes `section_renderers` keyword-only. The How-to example already uses the implemented argument name. [Explanations](docs/Explanations.md#gradio-editor) · [Constructor](src/apprc_dev/packaging/gui/src/apprc_gui/view.py#L60) · [How-to example](docs/How-To-User-Guides.md#add-a-gradio-settings-page)
- **Context:** A reader following the explanatory signature gets an unexpected keyword error when providing a registry manager.
- **Suggested next step:** Use the implemented signature and link the example. Verify the named arguments against the source and existing editor tests. The API requires no change.

<a id="csc-23"></a>

## P2 / E3 [Bug risk] - *Print editable update retry commands on their own lines*

- **Area:** Editable update sync and registration failure output.
- **Observed while:** Following the recovery directions after a fast-forward or a failed refresh.
- **Why not fixed now:** The follow-up needs exact output checks for POSIX and PowerShell command rendering.
- **Evidence:** The planner already quotes the command and environment. Both the sync exception and registration failure append a sentence period directly to the rendered command. On POSIX a pasted `uv sync --locked.` changes the final argument. On Windows the rendered quoted argument also acquires trailing punctuation as shell input. The how-to tells users to retry with the printed command. [Command rendering](src/apprc/distribution/runtime/update.py#L64) · [Sync retry](src/apprc/distribution/runtime/_update_handoff.py#L150) · [Registration retry](src/apprc/distribution/runtime/_update_handoff.py#L183) · [User guide](docs/How-To-User-Guides.md#update-an-application)
- **Context:** Recovery is most important when Git has advanced and synchronization or registration is still pending. Output should identify the completed phase, the working directory, and a command users can copy as written.
- **Suggested next step:** Render the command on a separate line without sentence punctuation. Reuse the existing argument quoting and test exact command boundaries with spaces and apostrophes. Keep the current update retry and registration-only alternatives. [Partial-failure test](tests/test_distribution_update.py#L181)

<a id="csc-24"></a>

## P3 / E3 [Docs drift] - *Describe workspace reconnect file creation before confirmation*

- **Area:** Textual reconnect prompt and `WorkspaceManager.repoint_workspace()`.
- **Observed while:** Tracing the Textual action from path selection to the registry update.
- **Why not fixed now:** The follow-up should align the prompt with the already established initialization behavior.
- **Evidence:** Both Textual dialogs promise a registry-only update without file creation. The manager ensures the ordinary workspace dotenv in the destination before recording the root. The editor workflow test prepares that dotenv in advance, so it does not exercise the promised file behavior in an uninitialized directory. [Prompt and confirmation](src/apprc/interfaces/tui/editor/workspace_editing.py#L112) · [Repoint implementation](src/apprc/services/workspaces.py#L206) · [Editor test](tests/test_config_tui_editor.py#L232)
- **Context:** Users must be able to tell before confirming that reconnect can initialize settings in an existing directory.
- **Suggested next step:** Describe the ordinary dotenv creation if missing at both prompts and check the CLI help and reconnect guide for compatible terminology. Add an existing-directory case without a dotenv. Preserve repoint behavior and the separate explicit secret repair action.

<a id="csc-25"></a>

## P3 / E3 [Code smell] - *Retire the unused missing-archive prune operation*

- **Area:** Workspace registry maintenance.
- **Observed while:** Tracing archive visibility and removal through the CLI and Textual.
- **Why not fixed now:** Check for intentional standalone or external use before removal.
- **Evidence:** `prune_missing_archived_workspaces()` appears in its module export list and definition only. No tracked caller, documented use, facade export, or test uses it at the reviewed revision. The manager exposes explicit removal of one archive record, and Textual handles missing archive files as visible state. [Unused operation](src/apprc/user_files/workspace_roots/registry.py#L485) · [Explicit removal](src/apprc/services/workspaces.py#L251) · [Workspace selection states](src/apprc/interfaces/tui/workspaces/selection.py)
- **Context:** Keeping an unowned registry mutation suggests there may be a supported automatic pruning path. A missing archive can be on temporarily disconnected storage, which makes explicit removal meaningful.
- **Suggested next step:** Check consumers of the internal module export, then remove the helper and its `__all__` entry if no supported caller depends on it. Keep missing archive display and explicit record removal. A consumer importing the internal helper directly would need to change.

<a id="csc-26"></a>

## P2 / E2 [Bug risk] - *Recheck workspace records after acquiring locks*

- **Area:** Workspace archive, restore, and unregister operations.
- **Observed while:** Following the archive and unregister leads from the previous move finding.
- **Why not fixed now:** Restore needs separate treatment for a registry-selected archive and an explicitly supplied import.
- **Evidence:** Archive and unregister capture a live record before taking the registry and resource locks and then act without comparing the captured record. Restore similarly resolves its archived source before locking, and the registration callback removes an archive row by name. If a repoint or archive refresh wins the lock first, a queued archive can record the old root, unregister can remove the changed record, or restore can consume the newer archive row after extracting the earlier archive. [Unregister](src/apprc/services/workspaces.py#L233) · [Archive](src/apprc/services/workspaces.py#L296) · [Restore](src/apprc/services/workspaces.py#L341) · [Archive-row commit](src/apprc/user_files/workspace_roots/registry.py#L149)
- **Context:** The earlier move fix verifies its captured live record once the locks are held. That invariant is just as useful where the selected record determines the filesystem action or the row consumed. The observed gap is in the lock-time comparison. The interleavings still need regression cases. [Move check](src/apprc/services/workspaces.py#L279) · [Previous finding](code-smells.md#csc-12)
- **Suggested next step:** Use the move's stale-selection rule for live workspace actions. For restore, bind any consumed archive row to its captured identity and define when explicit import consumes a saved row. Preserve the existing lock ordering and test a repoint or archive refresh winning the lock with deterministic barriers.

<a id="csc-27"></a>

## P2 / E2 [Bug risk] - *Make private companion failures consistent with workspace commit status*

- **Area:** Workspace registration and archive restore.
- **Observed while:** Following the ordinary dotenv, registry, and private companion through the success and failure paths.
- **Why not fixed now:** The follow-up needs a consistent outcome for optional private companion setup and an actionable recovery path.
- **Evidence:** Both manager routes call `ensure_secret_file()` after committing the live workspace. During restore, the extraction layer has already finished the transaction and attempted backup cleanup by then. `ensure_secret_file()` can return an unavailable status, which the managers ignore, or raise during creation or ACL setup, which the managers propagate as an operation failure after the workspace is already live. [Registration order](src/apprc/services/workspaces.py#L150) · [Restore order](src/apprc/services/workspaces.py#L381) · [Backup cleanup](src/apprc/user_files/workspace_roots/archive.py#L299) · [Companion creation](src/apprc/user_files/env_files/secrets.py#L99)
- **Context:** A caller can retry after a reported failure and encounter an already registered workspace. If the companion is optional, the user needs a committed result and repair guidance. If it is required, setup belongs before the commit while recovery remains possible.
- **Suggested next step:** Verify the existing ordinary-workspace and private-file contracts and choose the matching boundary. Keep private-permission checks and report the committed workspace state. Test an unavailable companion and a controlled creation failure for both routes, including preservation of any previous destination when the failure occurs before commit.

<a id="csc-28"></a>

## P3 / E2 [Tooling] - *Address the multithreaded fork warning in coordination tests*

- **Area:** Multiprocess installation finalization regression tests.
- **Observed while:** Running the local core suite on Python 3.14.2.
- **Why not fixed now:** An alternate start method must retain the deterministic ordering of the existing regression cases.
- **Evidence:** Three coordination cases emit Python's warning about forking a multithreaded test process. They still pass. Their common helper selects the `fork` multiprocessing context and the file skips Windows for its POSIX fork barriers. [Coordination helper](tests/test_installation_finalization_coordination.py#L115)
- **Context:** The tests protect namespace retirement and stale writers from process interleavings. Changing how processes start can invalidate that evidence if the synchronization or inherited state changes.
- **Suggested next step:** Identify which fixtures depend on inherited process state, then test an explicit start method or standalone workers using the existing barriers. Confirm the original interleavings and exercise repeated runs before changing CI or suppressing the warning.

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
- **Suggested next step:** Leave the native jobs disabled while this work is deferred. When suitable environments are available, validate native Windows install and uninstall, ACLs, shortcuts, and standalone dependencies first. Then investigate the recorded macOS path, interpreter, and secret/UI failures. Preserve containment and private-permission contracts; do not introduce runner, billing, or security changes implicitly.

<a id="p3--e3-bug-risk---verify-managed-desktop-shortcuts-on-windows"></a>

- **Desktop shortcut verification (Windows):** The automated test uses a stand-in for Windows Script Host. Verify shortcut creation, launch, and removal for managed and editable installs on native Windows. Check the icon in Windows Installed apps and the classic-console uninstall window.
- **Executable version verification (Windows):** Check the actual PowerShell command, numeric and textual versions, prerelease flag, and uninstall entry on a fresh PersoDB installation and after an update replaces its launcher. [Windows verification](docs/Development.md#verify-on-windows)

<br>
