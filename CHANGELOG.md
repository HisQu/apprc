# Changelog

All notable changes to `apprc` will be documented in this file.

This project follows Semantic Versioning.

## Unreleased

No changes yet.

## 0.15.2 - 2026-06-26

### Breaking changes

  - Breaking: `setup_logging()` now requires the `apprc[logging]`
    optional dependency because `structlog` is no longer installed by the base
    package.
    Affected: Users calling `setup_logging()` after installing bare `apprc`.
    Migration: Install AppRC with `python -m pip install "apprc[logging]"` or
    add `apprc[logging]` to the application's dependency declaration.
