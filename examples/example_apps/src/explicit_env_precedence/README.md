# Explicit Env Precedence Example

`explicit_env_precedence` demonstrates a storage-only app where explicit
env-file values can override or defer to shell env values.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- `APPRC_EXAMPLE_PRECEDENCE_ROOT` must point at a storage root. The root env
  file sets it to the generated `alpha` storage.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-explicit-env-precedence run
```

This setup fixes the common failure where the CLI has no storage selector.

## Commands

```bash
apprc-explicit-env-precedence run
apprc-explicit-env-precedence --env-file examples/example_app_disk_files/.apprc-example-explicit-env-precedence/.env run
apprc-explicit-env-precedence --env-file examples/example_app_disk_files/.apprc-example-explicit-env-precedence/.env --env-file-overrides-os-environ run
```

## Upgrade Options

Use `storage_only` for a smaller storage-selected app. Use `cli_runtime` when
selector handling must run inside a larger app-owned Typer callback.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Integration guide](../../../../docs/How-To-User-Guides.md#2-integrate-apprc)
