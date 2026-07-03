# Env Only Example

`env_only` demonstrates `rc.AppRC.env_only(...)`: package defaults, explicit
env files, and shell env, with no storage root.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- No storage directory is required.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-env-only config doctor
```

The app uses `config/.env.shared` from the package and the generated app-wide
file under `examples/example_app_disk_files/xdg-config-home/`.

## Commands

```bash
apprc-env-only run
apprc-env-only config paths
apprc-env-only config show --json
```

## Upgrade Options

Use `app_wide_config` when users should edit app-wide defaults through AppRC.
Use `storage_only` when each project or workspace needs its own selected
storage root.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Integration guide](../../../../docs/How-To-User-Guides.md#2-integrate-apprc)
