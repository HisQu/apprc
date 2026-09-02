# Storage Only Example

`storage_only` demonstrates `rc.AppRC(..., storage=rc.Storage(...))`: one
active storage root with storage-local values and optional names.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- `APPRC_EXAMPLE_STORAGE_ROOT` must point at a storage root. The root env file
  sets it to the generated `alpha` storage.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-storage-only config doctor
```

The bootstrap helper writes the active storage under
`examples/example_app_disk_files/.apprc-example-storage-only/storages/alpha`.

## Commands

```bash
apprc-storage-only run
apprc-storage-only config storage list
apprc-storage-only config show --json
```

The `app_wide_storage` scenario uses the same declaration shape and focuses on
app-level overrides. Use `cli_runtime` when a custom callback must prepare
additional runtime state.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Storage commands reference](../../../../docs/References.md#public-interfaces)
