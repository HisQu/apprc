# Changelog

All notable changes to `apprc` will be documented in this file.

This project follows Semantic Versioning.

<br>

### Table Of Contents

1. [Changelog](#changelog)
2. [\[Unreleased\]](#unreleased)
3. [0.16.3 - 2026-06-29](#0163---2026-06-29)
4. [0.16.2 - 2026-06-28](#0162---2026-06-28)
5. [0.16.1 - 2026-06-27](#0161---2026-06-27)
6. [0.16.0 - 2026-06-26](#0160---2026-06-26)
7. [0.1.0 - 2026-06-02](#010---2026-06-02)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### ➕ Added

  - Added a Graphigs-backed structured dotenv/config-file map showing where
    AppRC keeps each `.env` and TOML file, which `AppConfigKit` shapes use
    them, and how startup inputs feed runtime config.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.3 - 2026-06-29

<br>

### ➕ Added

  - Added layered Typer integration helpers: `mount_config_cli(...)`,
    `CliBootstrapOptions`, AppRC Typer context metadata, reusable host-level
    option aliases including `COMMON_HOST_FLAG_OPTIONS` and
    `COMMON_HOST_VALUE_OPTIONS`, `MountConfigCliStateFactory`, `CliArgvProvider`,
    `ConfigCliBridge`, `ConfigCliSession`, `ConfigCliStateFactory`,
    `BootstraplessCommand`, `HostCliBootstrapPolicy`, and configurable config
    bootstrap skip policies.

  - Added Graphigs-backed docs figure scripts for regenerating
    `docs-reading-map.svg` and `apprc-runtime-layers.svg`.

  - Added and placed Graphigs-backed graphical abstracts for the README
    overview, README system model, and runtime bootstrap docs.

<br>

### 💔 Changed

  - Improved Graphigs-backed graphical abstract layouts with clearer groups,
    a wide README hero format, looser labels, and documented figure color
    roles.

  - Tightened the new Typer convenience helper API before its first release:
    custom `mount_config_cli(...)` state now requires `state_factory=...`,
    generated config group renaming uses `config_group_name=...`, and explicit
    mount hook parameters replace loose keyword forwarding.

  - Refactored `mount_config_cli(...)` to use `ConfigCliBridge` internally so
    host-callback integrations and the convenience mount share one AppRC
    context, skip-policy, generated config group, and state-validation path.

  - Tightened `HostCliBootstrapPolicy` and `ConfigCliBridge` validation so
    help-like option values do not skip bootstrap, host option sets extend
    AppRC defaults, and direct config bootstrap policies cannot drift from the
    bridge config group name.

  - Renamed unreleased bridge policy option-extension parameters to
    `extra_host_flag_options=...` and `extra_host_value_options=...`, renamed
    the mount helper factory alias to `MountConfigCliStateFactory`, and made
    structurally recognized host command help skip runtime bootstrap without
    treating option values such as `--text --help` as help requests.

  - Renamed unreleased bootstrapless host-command declarations from
    `actions=...` to `exact_actions=...`, added `action_prefixes=...` for
    command subtrees with child options, and moved generated config skip
    composition fully under `ConfigCliBridge` so `HostCliBootstrapPolicy` only
    declares host-command additions.

  - Simplified `ConfigCliBridge(...)` defaults so `ConfigCliBridge(kit)` uses
    `DefaultConfigCliState`, while custom state still requires a
    `state_factory`. Skipped bridge bootstrap now reports `session.state is
    None` and leaves preexisting host-owned `ctx.obj` values untouched.

  - Made `HostCliBootstrapPolicy()` the default for `ConfigCliBridge(...)` and
    `mount_config_cli(...)`, added `bootstrap_policy=...` to the mount helper,
    rejected empty bootstrapless action paths, and tightened host help parsing
    so `run --help` skips bootstrap while `run -- --help` remains runtime data.

  - Refactored the generated Typer CLI internals to centralize command-token
    parsing, route generated config hooks through one internal option bundle,
    and split state/context resolution out of the command handler base class.

<br>

### 🔨 Fixed

  - Fixed runtimeful generated config commands with custom state so they fail
    clearly when AppRC bootstrap ran but the host callback did not leave the
    declared `state_type` on `ctx.obj`, while bootstrapless config commands
    still use AppRC's stored context.

  - Fixed generated config group mounting so `ConfigCliBridge(...)` and
    `mount_config_cli(...)` reject host Typer apps that already own the
    requested config command or group name.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.2 - 2026-06-28

<br>

### 💥 Breaking Change Summary

  - Breaking: `get_logger(NAME)` now raises `RuntimeError` when `NAME` already
    belongs to a pre-existing non-`AppLogger`.
    Affected: Integrations that create stdlib loggers before requesting an
    AppRC semantic logger for the same name.
    Migration: Call `install_app_logger_class()` or `get_logger(NAME)` before
    `logging.getLogger(NAME)` for names that need AppRC semantic helpers, or
    keep using the existing plain logger directly.

  - Breaking: `extract_archive(...)` now refuses to restore into a non-empty
    destination unless `replace_existing=True` is passed.
    Affected: Integrations that called `extract_archive()` to merge or replace
    existing directories.
    Migration: Restore into an empty directory, or prompt/confirm externally
    before calling `extract_archive(..., replace_existing=True)`.

  - Breaking: Blank or whitespace-only storage root text now raises
    `StorageRootPathError` instead of resolving to the current directory.
    Affected: CLI or API callers passing `""` or whitespace as a storage root.
    Migration: Pass `.` explicitly when the current directory is intended.

<br>

### ➕ Added

  - Added public `ConfigSelectorContext` plus context-aware config hooks:
    `active_storage_root_with_context(state, selector_context)` and
    `initial_storage_with_context(state, selector_context)`.

  - Added `replace_existing=False` to `extract_archive(...)` so callers must
    opt in before replacing a non-empty destination.


<br>

### 🔨 Fixed

  - Fixed storage-free generated `config edit` commands so app state objects no
    longer need to define a storage selector field.

  - Fixed storage archive creation so symlinks and in-archive hardlinks are
    rejected before any archive file is written.

  - Fixed generated `config --help` and `<config subcommand> --help` so help
    output does not require runtime storage readiness.

  - Fixed skipped-bootstrap config commands so host-level `--env-file` storage
    selectors and `--env-file-overrides-os-environ` participate in storage
    selection without mutating `os.environ`.

  - Fixed `config storage add` and `config storage remove` so root
    `--env-file` values can select the named-storage index through
    `<APP>_APPRC_TOML`.

  - Fixed storage setup, registry writes, selector resolution, and TUI storage
    registration so blank storage roots are rejected consistently.

  - Fixed storage registration so corrupt existing registries are detected
    before storage directories or dotenv files are created.

  - Fixed storage registration rollback so failed registry writes remove only
    empty artifacts created by that call and preserve existing storage content.

  - Fixed archive restore so all members are validated before extraction, the
    restore is staged in a sibling temp directory, and non-empty destinations
    are replaced only after an explicit opt-in.

  - Fixed TUI storage deletion so the registry row is removed before directory
    deletion; deletion failures now warn without recreating the row.

  - Fixed config help detection to honor custom host-level value options and to
    ignore `--help` or `-h` after a `--` separator.


<br>

---

<br>

<!-- ======================================================== -->

# 0.16.1 - 2026-06-27

<br>

### 💥 Breaking Change Summary

  - Breaking: `StorageMode` and `storage_mode=` were removed from the public
    API.
    Affected: Integrations importing `StorageMode` or passing `storage_mode=`.
    Migration: Use `AppConfigKit.env_only(...)`,
    `AppConfigKit.storage_only(...)`, `AppConfigKit.app_wide_config(...)`, or
    `AppConfigKit.app_wide_storage(...)`.

  - Breaking: AppRC no longer reads or writes `.env.global` and `.env.local`.
    Affected: Users with existing app-wide values in `.env.global` or
    storage values in `.env.local`.
    Migration: Move app-wide values to `.env.apprc-app` and storage values to
    `.env.apprc-storage`. `config doctor` reports legacy-file warnings.

  - Breaking: Runtime bootstrap, `config paths`, `config doctor`, and editor
    open are zero-write.
    Affected: Users and tests that expected normal runtime reads to create the
    config home, app-wide dotenv, storage dotenv, or `<app>.apprc.toml`.
    Migration: Run `config app init`, `config setup`, or
    `config storage add NAME PATH` when files should be created.

  - Breaking: Top-level generated storage commands were removed.
    Affected: Users running `config init` or `config list`.
    Migration: Use `config storage add NAME PATH`,
    `config storage list`, and `config storage remove NAME`.

  - Breaking: App-wide and storage writes now use explicit scopes when both
    writable layers are active.
    Affected: Users running `config set KEY VALUE` after activating both
    `.env.apprc-app` and a storage root.
    Migration: Pass `--scope app` or `--scope storage`.

  - Breaking: The Textual editor no longer infers a write target when
    app-wide and storage scopes are both writable.
    Affected: Users pressing Enter or Ctrl+S in the value editor while both
    writable layers are active.
    Migration: Click `Save App-wide` or `Save Storage`.

  - Breaking: Public filename constructor arguments were renamed.
    Affected: Integrations passing `apprc_toml_filename`,
    `global_env_filename`, or `local_env_filename`.
    Migration: Use `index_filename`, `app_wide_env_filename`, and
    `storage_env_filename`.

  - Breaking: Public local-env helper names were removed.
    Affected: Integrations importing `LocalEnvUpdate`, `local_env_path`,
    `read_local_env`, `write_local_env`, `set_local_env_value`, or
    `clear_local_env_value` from AppRC facades or storage modules.
    Migration: Use `EnvFileUpdate`, `storage_env_path`, `read_env_file`,
    `write_env_file`, `set_storage_env_value`, and
    `clear_storage_env_value`. Use `set_env_file_value` and
    `clear_env_file_value` for app-wide or other explicit env-file paths.

<br>

### ➕ Added

  - Added explicit capability constructors:
    `AppConfigKit.env_only(...)`, `AppConfigKit.storage_only(...)`,
    `AppConfigKit.app_wide_config(...)`, and
    `AppConfigKit.app_wide_storage(...)`.

  - Added `config paths` to show declared capabilities, active layers,
    candidate paths, selected storage, named-storage index status, and
    `writes: none`.

  - Added `config app init`, `config storage add NAME PATH`,
    `config storage list`, and `config storage remove NAME`.

  - Added doctor statuses `app_config_not_ready` and
    `named_storage_not_ready`.

<br>

### 💔 Changed

  - Changed runtime bootstrap precedence to packaged `.env.shared`,
    app-wide `.env.apprc-app`, storage `.env.apprc-storage`, explicit env
    files, and existing `os.environ`.

  - Changed storage selector resolution so path selectors work without a
    named-storage index, while named selectors use `<app>.apprc.toml` only when
    the index is allowed and exists.

  - Changed the Textual editor to show layer-oriented source columns:
    `Effective`, `Shell`, `App-wide`, `Storage`, `Default`, and `Explanation`.

  - Changed `<APP>_APPRC_TOML` to mean only named-storage index relocation.

  - Changed `config setup` to follow the constructor instead of prompting for
    optional upgrades.

  - Changed the Textual editor to hide named-storage management controls when
    named storage is disabled, while keeping active path editing available.

<br>

### 🗑️ Removed

  - Removed `StorageMode`.

  - Removed `config init` and `config list`.

  - Removed `.env.global` and `.env.local` fallback reads.

<br>

### 🔨 Fixed

  - Fixed storage-only runtime use so a single `APP_STORAGE=/path` selector no
    longer requires a config-home file or named-storage index.

  - Fixed optional named-storage handling so path selectors ignore corrupt
    optional indexes at runtime and report them as doctor warnings, while bare
    named selectors fail only when they need the invalid index.

  - Fixed `config edit` so host-level storage selectors are honored and editor open
    remains zero-write when optional named-storage indexes are corrupt but not
    needed.

  - Fixed `config doctor` so corrupt optional indexes are warnings when no
    selector exists or the active selector is path-like.

  - Fixed storage-env helper writes so storage roots must already exist, and
    no-op clears no longer create empty dotenv files.

  - Fixed `config setup` for app-wide storage constructors so config-home
    errors are reported as clean CLI validation errors.

  - Fixed Textual editor source-copy buttons so app-wide and storage copy
    actions copy only actual source values.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.0 - 2026-06-26

<br>

### 💥 Breaking Change Summary

  - Breaking: `setup_logging()` now requires the `apprc[logging]`
    optional dependency because `structlog` is no longer installed by the base
    package.
    Affected: Users calling `setup_logging()` after installing bare `apprc`.
    Migration: Install AppRC with `python -m pip install "apprc[logging]"` or
    add `apprc[logging]` to the application's dependency declaration.

<br>

---

<br>

<!-- ======================================================== -->

# 0.1.0 - 2026-06-02

<br>

### ➕ Added

- Released `apprc`.
- Added src-layout packaging, Typer CLI entrypoints, AppRC configuration, documentation, tests, and maintainer tooling.
