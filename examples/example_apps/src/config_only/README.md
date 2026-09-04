# Config Only Example

`config_only` demonstrates an AppRC declaration with no storage root. It loads
package defaults, per-user dotenv values, explicit env files, and shell values.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- No storage directory is required.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-config-only config doctor
```

The app uses `config/apprc.defaults.env` from the package and the generated
`apprc.user.env` below
`examples/example_app_disk_files/apprc-directories/`.

## Commands

```bash
apprc-config-only run
apprc-config-only config paths
apprc-config-only config show --json
```

Use `config_with_storage` when each project or workspace needs a selected
storage root.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Integration guide](../../../../docs/How-To-User-Guides.md#integrate-apprc)
