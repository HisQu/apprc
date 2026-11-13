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
3. [0.34.0 - 2026-11-13](#0340---2026-11-13)
4. [0.33.0 - 2026-11-11](#0330---2026-11-11)
5. [0.32.0 - 2026-11-10](#0320---2026-11-10)
6. [Older releases](CHANGELOG-ARCHIVE.md)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### 💥 Breaking changes
- Breaking: Applications now mount `config`, optional `workspace`, and configurable `app` groups instead of root maintenance commands. Migrate `paths` to `app paths`, all diagnostic commands to `app doctor`, saved installation actions to `app repair|uninstall|migrate`, and resource operations to `app data|cache|state`. Use `config setup` instead of `config init`. Public `purge` and generic resource `info`/`init` commands are removed; their Python maintenance APIs remain available.
- Breaking: CLI integrations must opt into saved installation management with `installation_management=True`, use nested returned-group keys such as `app.cache`, and register custom resource commands through `resource_group_extensions`. Doctor JSON now always includes `status`, `checks`, and `installation`; `--verbose` adds `details.paths`, `details.configuration`, `details.resources`, and `details.host`. No compatibility command aliases are retained.

<br>

### ➕ Added
- Added opt-in ordered root help through `rc.cli.AppRCRootGroup`, with separate application and AppRC panels while preserving normal Typer parsing and nested help.
- Added optional root `launch` through an explicitly supplied `LauncherSpec`, opening the existing Textual management launcher without resolving business settings. Explicit installer and local diagnostic registrations integrate existing application-owned behavior without discovering or replacing it.

<br>

### 💔 Changed

<br>

### ⚠️ Deprecated

<br>

### 🗑️ Removed

<br>

### 🔨 Fixed
- Corrected the one-line installation requirement ranges to include the published 0.34 release.

<br>

### 🔒 Security

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

# 0.32.0 - 2026-11-10

Includes the changes previously listed under unpublished 0.31.0 and Unreleased.

<br>

### 💥 Breaking changes

- Breaking: Native Linux appdata now uses `<native-user-data>/<app-id>/appdata`,
  beside durable `installation/`, instead of owning the whole app container.
  Affected: applications and users with an existing native Linux appdata root.
  Migration: stop old consumers, preview `installation migrate --dry-run`, and
  execute an explicit ownership/provider-reviewed migration. Unknown payload
  requires the owning application's inventory; startup never selects a new empty
  store in place of a recognized legacy root.
- Breaking: `AppPaths` now requires a captured `installation` snapshot and its
  `source` can be `"installation"`. Affected: callers constructing `AppPaths`
  directly or exhaustively handling layout provenance. Migration: prefer
  `MyRC.paths(...)`; intentional manual construction must preserve the snapshot
  from `MyRC.installation().inspect().snapshot`. Do not rediscover paths while
  refreshing an existing invocation.

- Breaking: Replaced `Storage`/`storage` and `ResolveOptions.storage` with
  `Workspaces`/`workspace`, and replaced `ResolvedConfig.selection` with
  `workspace`. Affected: applications declaring or selecting AppRC storage,
  including section `requires_storage` declarations. Migration: declare
  `Workspaces()` only when a workspace selector is needed; use `workspace=...`
  and `workspace_required=True`; read `resolved.workspace` and
  `resolved.workspace_issues`. Use `WorkspaceManager` for registry operations.
  AppRC does not read or upgrade old `storages` TOML records or old storage
  dotenv filenames.
- Breaking: Replaced `apprc_dir`, `apprc_dir_env_key`, `legacy_app_ids`, and
  storage-path resolution with `Paths`, `Layout`, `AppPaths`, `paths()`, and
  `ensure_path()`. Affected: applications configuring managed directories or
  relying on `*_APPRC_DIR`/old storage variables. Migration: independently
  declare `Paths(config=True, appdata=True, cache=True, state=True)` for the
  components actually used; choose `Layout.native()` or
  `Layout.single_root(root)`; update users to the new `<PREFIX>_LAYOUT` and
  `<PREFIX>_ROOT` pair. Normal startup never searches for or automatically
  migrates legacy data; explicit migration is limited to reviewed supported
  ownership/installation formats.
- Breaking: Replaced `mount_config_cli`, `mount_appdata_cli`, and
  `mount_config_group` with grouped `mount_app_cli`/`mount_app_groups`.
  Affected: Typer applications mounting prior commands. Migration: mount the
  new grouped adapter and update `appdata clean`/`appdata paths` to root
  `purge`/`paths`; provide explicit maintenance handlers for application-owned
  operations. No compatibility aliases remain.
- Breaking: Replaced the old `apprc.toml` storage registry schema and
  `apprc.storage.env` / `apprc.storage.secret.env` layer names. Affected:
  applications reading or editing those AppRC-owned files. Migration: create a
  new workspace registry through `WorkspaceManager` and use the documented
  `apprc.workspace.env` / `apprc.workspace.secret.env` names. Do not rename or
  convert old files in place; manually preserve or separately export any data
  users choose to retain.

<br>

### ➕ Added

- Added independent opt-in config, appdata, cache, and state paths using native
  platform locations or an explicit single-root layout. Path inspection is
  read-only; `ensure_path()` initializes only the requested enabled component
  with an ownership marker.
- Added explicit `WorkspaceManager` operations and category-specific maintenance
  providers, plus grouped `paths`, `doctor`, category, workspace, and `purge`
  commands. Unsupported provider operations are not mounted.
- Added fixed native `installation/installation.json` authority independent of
  config, appdata, cache and disposable state. Saved absolute placement survives
  upgrades and outranks declared defaults; invocation/environment overrides
  remain local to that invocation. Unmanaged editable pip use needs no record.
- Added typed installation inspection, revision/generation-checked operations,
  explicit legacy migration, resumable repair, reconnectable program-only
  removal and confirmed complete removal that preserves unknown content.
  Matching failed uninstalls reuse recorded checkpoints. Default complete-removal
  inventories recognize owned standard config files and resource markers;
  custom payload still requires provider inventory or retained-data consent.
- Added native-appdata validation that recognizes the exact persistent sibling
  resource lock while retaining unknown-content and link checks. Reinstall and
  retained repair preserve both user work and the existing coordination inode.
- Added explicit verified-source legacy replacement with independent historical
  RECORD observation, preserved recorded interpreter/backend, a read-only pending
  predicate and resumable pre-mutation authority. Recovery inputs and an owned
  recovery entry precede initial pending-authority publication; strict new-source
  observation precedes old-controller retirement. Historical source provenance
  is never fabricated.
- Added `apprc-core[distribution]` authoring APIs, strict external templates and
  deterministic PEP 723/zipapp support bundling complete ordinary shared modules
  with repository-owned install/uninstall composition. No lifecycle inheritance,
  hook registry, installed-app bootstrap dependency or hidden AppRC download is
  required; application-specific actions remain explicit Python calls.
  Standalone management dependencies remain separate from exact application
  runtime constraints, including applications with no runtime dependencies.
- Added explicit typed re-exports from `apprc.distribution` and
  `apprc.distribution.runtime`; consumers use the supported public facades rather
  than implementation-module imports.
- Added verified immutable-main, release-sdist and explicit-wheel acquisition
  with operation-owned source staging and observed installed `RECORD`
  fingerprints. Saved source checks remain usable after temporary sources are
  removed.
- Added public `bind_install_support()` composition for current-platform,
  machine-bound recovery support before legacy activation. Remote Windows `.cmd`
  entries carry the shared PowerShell bootstrap instead of requiring an adjacent
  helper; remote PowerShell helpers also support downloaded-text invocation.
- Added grouped `installation` management commands and an optional Textual
  launcher with one reusable editor screen/event loop, foreground-child handling,
  and actual-process removal handoff. CLI, launcher and wrappers share the saved
  application-authored uninstaller, including its cleanup. Missing business
  settings or invalid installation authority remain diagnosable without
  manufacturing resource paths.

- Added a separate Actions artifact round-trip diagnostic with manual invocation,
  a narrowly scoped initial feature-branch push trigger, one-day retention, and
  documented exact-artifact cleanup.
- Added optional `installation_inventory` callbacks to the application CLI for
  exact provider-owned cleanup previews. Confirmed removal transports the
  accepted inventory to the saved controller; dry-run remains read-only, and
  retries reuse the inventory persisted in the pending operation.
- Added `default_cleanup_inventory()`, `encode_cleanup_inventory()`, and
  `decode_cleanup_inventory()` for composing application-owned cleanup with
  AppRC's default inventory and strict installation JSON transport.
- Added application-supplied maintenance providers through
  `AppRC.maintain(handlers=...)`, preserving the declared cleanup behavior in
  both preview and execution.

<br>

### 💔 Changed

- Restricted CI to Ubuntu: core checks retain Python 3.12, 3.13, and 3.14, and
  GUI/browser checks retain Python 3.12. Windows and macOS runtime and installer
  code remain, but those platforms are unverified by this CI policy;
  [known native test failures](BACKLOG.md#p2--e1-tooling---windows-and-macos-installation-ci-fails)
  remain unresolved. Green Linux CI does not establish native compatibility.
- Retained the last three published minor release lines, including their patch
  releases, in this changelog; older entries are preserved in the
  [changelog archive](CHANGELOG-ARCHIVE.md).

<br>


---

<br>
