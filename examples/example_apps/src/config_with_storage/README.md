# Config With Storage Example

`config_with_storage` demonstrates `rc.AppRC(..., storage=rc.Storage(...))`
with one active storage root, storage-local values, and optional storage names.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- `APPRC_EXAMPLE_STORAGE_ROOT` must point at a storage root. The root env file
  sets it to the generated `alpha` storage.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-config-with-storage config doctor
```

The bootstrap helper writes the active storage under
`examples/example_app_disk_files/.apprc-example-config-with-storage/storages/alpha`.

## Commands

```bash
apprc-config-with-storage run
apprc-config-with-storage config storage list
apprc-config-with-storage config show --json
```

Use `cli_runtime` when a custom callback must prepare additional runtime state.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Storage commands reference](../../../../docs/References.md#public-interfaces)
