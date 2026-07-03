# App-Wide Config Example

`app_wide_config` demonstrates `rc.AppRC.app_wide_config(...)`: app-wide
dotenv settings without a selected storage root.

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

The app-wide file is generated under
`examples/example_app_disk_files/xdg-config-home/apprc-example-app-wide-config/`.

## Commands

```bash
apprc-app-wide-config run
apprc-app-wide-config config paths
apprc-app-wide-config config show --json
```

## Upgrade Options

Use `app_wide_storage` when users need both app-wide defaults and
storage-local values.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Capability model](../../../../docs/Explanations.md#package-architecture)
