# App-Wide Storage Example

`app_wide_storage` demonstrates direct `rc.AppRC(...)` with `rc.Storage(...)`:
app overrides plus storage-local values selected by
`APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT`.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- The generated `alpha` storage root must exist.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-app-wide-storage config doctor
```

The bootstrap helper writes app files under the shared generated
`xdg-config-home` and storage-local files under the app sandbox.

## Commands

```bash
apprc-app-wide-storage run
apprc-app-wide-storage config storage list
apprc-app-wide-storage config show --json
```

Use `cli_runtime` when the host CLI needs app-specific callback state. Use
`explicit_env_precedence` when testing selector precedence with explicit env
files.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [Configuration files](../../../../docs/References.md#configuration-files)
