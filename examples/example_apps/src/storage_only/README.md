# Storage Only Example

`storage_only` demonstrates `rc.AppRC.storage_only(...)`: one active storage
root with storage-local dotenv values and optional named-storage registry.

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

## Upgrade Options

Use `app_wide_storage` when the app also needs app-wide editable defaults.
Use `cli_runtime` when a custom app callback must prepare additional runtime
state before commands run.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Storage commands reference](../../../../docs/References.md#public-interfaces)
