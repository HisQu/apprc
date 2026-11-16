# Changelog

All notable changes to `AppRC` will be documented in this file.

> [!IMPORTANT]
> ## Rules
> 1) Do not remove or change this header and TOC without very good reason. 
> 1) When bumping version, move the sub-sections from `[Unreleased]` to
>    the new version -section. Remove empty sub-sections under released
>    versions. Provide a new `[Unreleased]` section at the top of the
>    changelog with all sections empty (don't remove those).
> 1) Keep only the last three minor releases, including all their patch releases.
>    Put older releases into [CHANGELOG-ARCHIVE.md](CHANGELOG-ARCHIVE.md).
> 1) Do not remove emojis and use `<br>` and `---`.
> 1) Changelog entries must describe the final net difference from the
>    previous released version. Do not list intermediate pre-release
>    names, helper shapes, fixes, or refactors that were overwritten
>    before release.
> 1) Use `🔨 Fixed` only for defects in previously released behavior.
>    For new features, describe the final shipped behavior under `➕
>    Added`, even if the implementation went through pre-release fixes.



<br>

---

<br>

## Table Of Content

1. [Changelog](#changelog)
   1. [Table Of Content](#table-of-content)
2. [\[Unreleased\]](#unreleased)
3. [0.35.1 - 2026-11-16](#0351---2026-11-16)
4. [0.35.0 - 2026-11-16](#0350---2026-11-16)
5. [0.34.0 - 2026-11-13](#0340---2026-11-13)
6. [0.33.0 - 2026-11-11](#0330---2026-11-11)
7. [Older releases](CHANGELOG-ARCHIVE.md)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### 💥 Breaking changes

- Breaking: runtime implementation modules `controllers`, `removal`, and `_integration` are now `_uninstall_controller`, `uninstall_handoff`, and `_os_integration`. Update direct imports and handoff module invocations; runtime facade exports remain available.

- Breaking: `InstallationManager.plan_repair()` now plans only a new managed-runtime repair. Call `plan_resume()` to resume an incomplete install, replacement, or repair; the saved operation ID, candidate, and operation kind remain unchanged.

<br>

### ➕ Added

<br>

### 💔 Changed

- Native and editable installation reuse runtime-option declarations and placement construction. Diagnostic aggregation lives in the CLI diagnostics package; shared installation test fixtures no longer import other test modules.
- Install completion offers configuration only for missing required user settings without fallbacks. Non-interactive and `--skip-setup` invocations skip the offer; explicit `config setup` remains available.

- Uninstall orchestration follows explicit existing checkpoint phases with shared Windows registry handling. Application bridge actions use focused handlers behind common request and authority validation.

- Managed installation and repair share publication, registration, checkpoint, and activation handling while retaining distinct preparation and rollback evidence.

<br>

### ⚠️ Deprecated

<br>

### 🗑️ Removed

<br>

### 🔨 Fixed

- Setup completion uses the mounted maintenance group for `app paths` and `app doctor` guidance. AppRC-generated installation, maintenance, and workspace options and arguments now include help descriptions.

- A freshly rebuilt runtime candidate is no longer rebuilt again after a validation probe fails. Previously prepared candidates retain one recovery rebuild.

<br>

### 🔒 Security

<br>

---

<br>

# 0.35.1 - 2026-11-16

### 🔨 Fixed

- Native authoring and the embedded manager now accept uv >=0.11.6 instead of requiring exactly 0.13.6. Newer uv versions no longer require an AppRC release just to pass the version check.

<br>

---

<br>

# 0.35.0 - 2026-11-16

<br>

### 💥 Breaking changes
- Breaking: `app uninstall` now removes managed configuration, data, cache and state by default. Use `--keep-data` for the previous program-only behavior. Editable repositories remain by default; `--remove-repository` explicitly includes the checkout and its contents. The former `--complete`, `--category` and `--forget-retained` switches are removed.
- Breaking: CLI mounting no longer accepts `installation_hooks`. Declare optional lifecycle callbacks once in `[tool.apprc.distribution.hooks]` in `pyproject.toml`; packaged and editable registration use that declaration. Ordinary managed directory deletion no longer requires application inventory or cleanup callbacks.
- Breaking: Applications now mount `config`, optional `workspace`, and configurable `app` groups instead of root maintenance commands. Migrate `paths` to `app paths`, all diagnostic commands to `app doctor`, saved installation actions to `app repair|uninstall|migrate`, and resource operations to `app data|cache|state`. Use `config setup` instead of `config init`. Public `purge` and generic resource `info`/`init` commands are removed; their Python maintenance APIs remain available.
- Breaking: CLI integrations must opt into saved installation management with `installation_management=True`, use nested returned-group keys such as `app.cache`, and register custom resource commands through `resource_group_extensions`. Doctor JSON now always includes `status`, `checks`, and `installation`; `--verbose` adds `details.paths`, `details.configuration`, `details.resources`, and `details.host`. No compatibility command aliases are retained.
- Breaking: Managed installations now require a complete project snapshot embedded in native setup and use locked runtime slots instead of shared uv tools. Existing managed users must remove the old program using its matching old tools while retaining user data, then reinstall; schema-2 records are not converted automatically. Remote `--main`/`--version`, wheel/index installation, custom wheel compilation and runtime dependency injection are removed.
- Breaking: Distribution authors must use the project-snapshot/native-distribution builders and keep generated outputs in ignored `dist/` and `.cache/apprc/`. Standalone Python installers, shell/CMD/PowerShell lifecycle wrappers and generated source-tree support copies are removed. CLI integrations replace `installation_inventory` with typed `InstallationHooks` declarations; no compatibility aliases remain.

<br>

### ➕ Added
- Added explicit symbolic-link entries to cleanup inventories, with link identity checks and removal that leaves the target untouched.
- Added opt-in ordered root help through `rc.cli.AppRCRootGroup`, with separate application and AppRC panels while preserving normal Typer parsing and nested help.
- Added optional root `launch` through an explicitly supplied `LauncherSpec`, opening the existing Textual management launcher without resolving business settings. Explicit installer and local diagnostic registrations integrate existing application-owned behavior without discovering or replacing it.
- Added committed project snapshots with their exact `uv.lock`, workspace members and package resources, including ZIP assets, while excluding generated environments and build caches.
- Added first-class `app install -e` registration of an existing developer-owned checkout environment, without duplicating it or taking ownership of the checkout.
- Added an independent native management command that forwards application commands to the recorded active runtime, with runtime leases, recoverable slot activation and explicit reporting of unavailable application checks.

<br>

### 💔 Changed
- Added grouped configuration updates with revision-checked regular/private-file restoration, and optional host-owned Gradio section renderers for related settings and application validation.
- Managed and editable installation restore AppRC-owned pre-activation changes on caught failure, including command publication and partial Windows registration. Incomplete rollback retains recovery evidence; committed activation survives cleanup failures. Application data compatibility remains application-owned.
- Operation-created bridge and project staging directories apply private Windows ACLs before payload creation, and exact incomplete editable registrations can resume their recorded placement.
- CLI and launcher declarations defer editor and prompt implementations until use; help no longer imports those stacks. Editable registration compares existing environment directory identities and handles native Windows UNC file URLs with explicit platform and path diagnostics.
- Reordered opt-in root help to show host commands and options first, AppRC commands and runtime options next, and common help/completion options last. Cyan host and magenta AppRC headings and borders distinguish ownership; common controls are dim, descriptions remain neutral, and terminal color controls are respected.

<br>

### 🗑️ Removed
- Removed the initializer AST test that rejected explicit distribution facade exports.

<br>

### 🔨 Fixed
- Corrected the one-line installation requirement ranges to select the 0.35 release.

<br>

---

<br>

<!-- ======================================================== -->

# 0.34.0 - 2026-11-13

<br>

### 💥 Breaking changes

- Removed `render_bootstraps()` and the generated shell/PowerShell fetcher
  templates and fetcher artifacts. Affected: application authors calling that
  API or committing generated root installers and launchers. Migration: generate
  `app-install.py` and `app-launch.py` with the Rust-free artifact APIs and invoke
  them with `uv run --script`; use the optional native producer only when native
  release executables are required. The generated root `launch.sh` is no longer
  produced; Windows `launch.cmd` and `launch.ps1` remain.

### ➕ Added

- Added verified prepared-wheel bundle inputs to managed installation, using
  real uv overrides, exact runtime constraints and the complete locked graph.
  Wheel bytes and metadata are revalidated at the existing mutation boundaries;
  existing `runtime_overrides` retain their `--with` meaning.
- Added explicit pinned PyApp frontend compilation for Linux and Windows console
  targets, with authenticated dispatcher packaging and build reports. Ordinary
  Python artifact generation remains independent of Rust.
- Added the `runtime-python` distribution setting to select a managed CPython
  minor consistently for native wheel builds and uv installation, independently
  of the package compatibility range and PyApp's bootstrap interpreter.
- Native POSIX launch dispatch preserves the application process identity, so
  terminating the launcher stops the application instead of leaving it running.

<br>

### 💔 Changed

- Gave package reconciliation one installation stage while keeping support
  publication, registration, and transaction completion with its caller.
- Separated pending uninstall preparation and execution from committed
  finalization, preserving authority, containment, and recovery checks before
  readiness or mutation.
- Moved field-table widget population into the config editor's rendering layer,
  keeping displayed rows and immutable selection keys aligned.
- Grouped typed runtime facade exports without changing the public symbol set.
- Prepared dependency-import schemas before committing registry updates and
  removed the redundant combined dependency-key registry.
- Extracted config normalization, dependency-import preparation, and config
  bundle generation into private public-facade helpers, keeping registration
  state and validation-before-commit schema construction in `AppRC`.
- Shared materialized-directory source proof between immutable-main and
  release-sdist probes, preserving installed `RECORD` checks and diagnostics.
- Centralized deterministic ZIP serialization for standalone payloads,
  inspection bundles, and zipapps without changing archive settings.
- Shared file and directory privacy checks while preserving operation-boundary
  validation, platform-specific diagnostics, and coordination's POSIX owner check.

<br>

### 🔨 Fixed

- Kept saved repair usable after an interrupted package checkpoint whose current
  snapshot has no published support inventory, while retaining digest checks
  that reject unknown or modified repair installers.
- Reset inherited PowerShell module paths in checkout and standalone Windows
  CMD installers so PowerShell 7 callers cannot select incompatible built-in
  modules in Windows PowerShell. Caller environments and persistent execution
  policies remain unchanged.
- Declared the Windows `CloseHandle` signature so native process handles are
  closed without truncating their pointer-sized values.
- Selected all workspace projects in complete-development and CI sync commands,
  including the GUI from the locked workspace rather than a second install.
- Aligned example-workspace CLI and GUI requirements during release preparation
  and restored them on failure, so minor and major bumps keep the workspace resolvable.

<br>

---

<br>

<!-- ======================================================== -->

# 0.33.0 - 2026-11-11

<br>

### 💥 Breaking changes

- Breaking: Removed the unused `apprc.files.ConfigSetupError` export and
  `run_config_setup(..., allow_interactive_secret_repair=...)` plumbing.
  Affected: callers importing that error type or passing that setup parameter.
  Migration: handle setup's existing `ValueError`/`OSError` failures and use
  explicit `config secrets repair` for permission changes.
- Breaking: Removed `apprc.provenance.with_field_origin`.
  Affected: callers using that pure mapping-copy helper.
  Migration: use `{**origins, field_name: origin}` for a new mapping.
  `set_field_origin(instance, field_name, origin)` remains available for
  updating an existing configuration instance's origin metadata.
- Breaking: Removed the unused direct-dotenv helpers
  `set_workspace_dotenv_value`, `set_env_file_value`,
  `plan_workspace_dotenv_value_update`, `clear_workspace_dotenv_value`, and
  `clear_env_file_value` from `apprc.user_files.env_files` and its `updates`
  module. Affected: callers importing these low-level helpers.
  Migration: use `ConfigManager.plan_update()` or `plan_removal()`, then
  `apply_edit()`; the shared low-level plan/apply primitives remain available.
- Breaking: Installation authority now uses strict schema `2`. Affected: managed
  applications with schema-1 records. Old/unknown records remain read-only
  diagnostics; the SDK no longer translates or adopts them.
  Migration: finish old operations, back up data, retire the previous generation
  and its saved authority without deleting preserved resources, then reinstall.
  See the [upgrade procedure](docs/How-To-User-Guides.md#migrate-existing-applications).
- Breaking: Removed receipt adoption/replacement APIs and receipt-only migration
  types/arguments, including `InstallationManager.migrate_legacy()` and the
  `apprc.distribution.runtime` legacy receipt/replacement families.
  Affected: installer authors and direct callers of those APIs.
  Migration: remove legacy receipt cutover code and use a fresh current-format
  installation; current resource/layout migration remains supported.
- Breaking: Saved Python management support now uses canonical `management.py`
  and owned `management.json` binding data instead of generated launcher/uninstall
  policy and interpreter assignments in Python source.
  Affected: installer authors consuming private support filenames or parsing
  saved helpers. Migration: regenerate the complete support set through
  `install_support_files()` and remove old filename/source-shape assumptions.
  Public root launch/uninstall wrappers remain unchanged.

<br>

### ➕ Added

- Added explicit `reason` values to field inspection and secret-file status.
  CLI and GUI decisions no longer depend on the wording of display diagnostics.

<br>

### 💔 Changed

- Centralized immutable GitHub source identity parsing while retaining separate
  archive, installed RECORD, and filesystem verification.
- Gave shared uninstall process-identity and containment mechanics a leaf owner,
  removing the controller/removal dependency cycle while preserving the typed
  public runtime facade.
- Unified configuration origin tracking, preserving explicit overrides and
  Python-only field provenance when environment-backed settings are reloaded.
- Documented fresh-plan recovery after an interrupted secret migration, including
  safe partial progress and rejection of the original stale plan.
- Removed development import-path-absence and nonempty-facade assertions; supported
  API and installed-distribution ownership checks remain.
- Gave editor workspace presentation one post-action owner. Workflows use fresh
  action inputs rather than capturing the screen, and a failed registry reload
  no longer leaves stale workspace state editable or valid user editing locked.

<br>

---

<br>

<!-- ======================================================== -->
