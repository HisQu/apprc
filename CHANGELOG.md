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

  - Breaking: `AppConfigKit` and `AppConfigSpec` no longer require storage by
    default when `storage_env_key` is omitted.
    Affected: Integrations that expected AppRC to derive and require
    `<APP>_STORAGE` without explicitly declaring storage.
    Migration: Pass `storage_mode="required"` or `storage_env_key="<APP>_STORAGE"`
    when the application needs an active storage root.

  - Breaking: `<APP>_APPRC_TOML` is now only an override path for the AppRC
    TOML metadata file, not the switch that enables multi-storage behavior.
    Affected: Users and integrations that relied on setting
    `<APP>_APPRC_TOML` to move from single-storage path mode into
    multi-storage registry mode.
    Migration: Opt the app into required storage, then keep storage entries in
    the default `<config-home>/<app>.apprc.toml` or set `<APP>_APPRC_TOML` only
    when that metadata file must live somewhere else.

  - Breaking: AppRC bootstrap now inserts `.env.global` between packaged
    `.env.shared` and storage-local `.env.local`.
    Affected: Environments where the same key exists in `.env.shared` and the
    new `.env.global` file.
    Migration: Move values that should apply everywhere into `.env.global`, and
    keep per-storage overrides in `.env.local` when storage is required.

  - Breaking: Generated `config` commands gate storage registry workflows to
    storage-required apps and use `.env.global` for storage-free `show`, `set`,
    `edit`, `setup`, and `doctor` flows.
    Affected: Host apps that omitted `storage_env_key` but still exposed
    storage registry commands as part of their generated config CLI.
    Migration: Pass `storage_mode="required"` or `storage_env_key` for apps
    that need `config init`, `config list`, archive, or register workflows.

  - Breaking: Filename-style config inputs now accept only basenames.
    Affected: Integrations passing path-like values to `apprc_toml_filename`,
    `shared_env_filename`, `global_env_filename`, `local_env_filename`, or
    `app_config_file(..., filename)`.
    Migration: Pass only a file name for these attributes. Use
    `<APP>_APPRC_TOML` for a full AppRC TOML override path, and use
    `app_config_home(...)` or `app_config_file(...)` to build conventional
    config-home paths.

<br>

### Added

  - Added `platformdirs` as a runtime dependency behind AppRC config-home
    helpers.

  - Added `StorageMode`, `global_env_filename`, `.env.global` support, and
    public `app_config_home(...)` / `app_config_file(...)` helpers.

  - Added non-interactive creation of AppRC-managed config-home files:
    `.env.global` and `<app>.apprc.toml`.

  - Added `config_home` and `global_env` to `EnvBootstrapResult` and the
    generated `config doctor --json` payload.

  - Added the `config_not_ready` doctor status for AppRC config-home readiness
    problems.

  - Added `ConfigHomeError` for invalid AppRC-managed config-home paths and
    filename-style inputs.

<br>

### Changed

  - Changed runtime bootstrap so storage-disabled apps never require, write, or
    mutate `<APP>_STORAGE`.

  - Changed storage-required selector resolution so `.env.global` can provide a
    persistent selector fallback before packaged `.env.shared`.

  - Changed dotenv override helpers so `.env.global` and storage-local
    `.env.local` share the same read/write implementation while preserving the
    existing storage-local facade imports.

  - Changed `config doctor` to report config-home and `.env.global` readiness
    for storage-free apps instead of treating missing storage as central.

  - Changed generated setup output to print `<APP>_APPRC_TOML` exports only
    when the AppRC TOML path is custom. The config-home default no longer
    needs an export line.

<br>

### Deprecated

<br>

### Removed

<br>

### Fixed

  - Fixed `config doctor` so wrong filesystem types in the config home,
    `.env.global`, or AppRC TOML path report `config_not_ready` instead of
    silently appearing runnable.

  - Fixed skipped-bootstrap generated config commands so `config list` and
    `config edit` honor storage selectors stored in `.env.global`.

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
