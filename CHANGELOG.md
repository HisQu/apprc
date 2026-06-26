# Changelog

All notable changes to `apprc` will be documented in this file.

This project follows Semantic Versioning.

<br>

### Table Of Contents

1. [Changelog](#changelog)
2. [\[Unreleased\]](#unreleased)
3. [0.15.2 - 2026-06-26](#0152---2026-06-26)
4. [0.1.0 - 2026-06-02](#010---2026-06-02)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### 💥 Breaking Change Summary

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

# 0.15.2 - 2026-06-26

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
