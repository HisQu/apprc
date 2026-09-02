# App-Wide Config Example

`app_wide_config` demonstrates direct `rc.AppRC(...)` with per-user app config
and no selected storage root.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- No storage directory is required.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-app-wide-config config doctor
```

The app file is generated under
`examples/example_app_disk_files/xdg-config-home/apprc-example-app-wide-config/`.

## Commands

```bash
apprc-app-wide-config run
apprc-app-wide-config config paths
apprc-app-wide-config config show --json
```

Use `app_wide_storage` when users also need storage-local values.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Runtime config model](../../../../docs/Explanations.md#3-runtime-config-model)
