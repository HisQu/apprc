# Changelog

All notable changes to `apprc` will be documented in this file.

This project follows Semantic Versioning.

<br>

### Table Of Contents

1. [Changelog](#changelog)
2. [\[Unreleased\]](#unreleased)
3. [0.16.0 - 2026-06-26](#0160---2026-06-26)
4. [0.1.0 - 2026-06-02](#010---2026-06-02)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### Breaking changes

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

### Added

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

### Changed

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

### Deprecated

<br>

### Removed

  - Removed `StorageMode`.

  - Removed `config init` and `config list`.

  - Removed `.env.global` and `.env.local` fallback reads.

<br>

### Fixed

  - Fixed storage-only runtime use so a single `APP_STORAGE=/path` selector no
    longer requires a config-home file or named-storage index.

  - Fixed optional named-storage handling so path selectors ignore corrupt
    optional indexes at runtime and report them as doctor warnings, while bare
    named selectors fail only when they need the invalid index.

  - Fixed `config edit` so root storage selectors are honored and editor open
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

### ➕ Added

<br>

### 💔 Changed

<br>

### ⚠️ Deprecated

<br>

### 🗑️ Removed

<br>

### 🔨 Fixed

<br>

---

<br>

<!-- ======================================================== -->

# 0.1.0 - 2026-06-02

<br>

### ➕ Added

- Released `apprc`.
- Added src-layout packaging, Typer CLI entrypoints, AppRC configuration, documentation, tests, and maintainer tooling.
