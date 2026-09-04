# CLI Runtime Example

`cli_runtime` demonstrates `CliRuntime`: an app-owned Typer callback prepares
AppRC and app-specific runtime state before commands run.

## Requirements

- Install the example package from the repository checkout.
- Source `.env.example_apps` or use direnv.
- `APPRC_EXAMPLE_RUNTIME_ROOT` must contain a registered storage name.
- `--workspace` and `--model` are app-owned options for runtime commands.

## Setup

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-cli-runtime --workspace /tmp/apprc-workspace --model demo run
```

The `status` command is runtime-independent and can run without storage
bootstrap.

## Commands

```bash
apprc-cli-runtime --workspace /tmp/apprc-workspace --model demo status
apprc-cli-runtime --workspace /tmp/apprc-workspace --model demo run
apprc-cli-runtime config doctor
```

## Upgrade Options

Use this layout when the app has its own root callback, logging setup, or
state object. Split larger config areas into nested packages under
`config/sections/`, as this example does with `runtime/`.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
- [CLI integration reference](../../../../docs/References.md#public-interfaces)
