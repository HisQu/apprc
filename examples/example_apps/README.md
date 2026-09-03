# AppRC Example Apps

This directory is a dev-only editable package with runnable CLIs for each
AppRC integration scenario.

## Setup

With direnv, run `direnv allow` at the repository root. `.envrc` sources
`../../.env.example_apps` and bootstraps ignored disk files automatically.

Without direnv:

```bash
python -m pip install -e examples/example_apps --no-build-isolation
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
```

Generated files live in `../example_app_disk_files/`. They are runtime files,
not source templates.

## Source Packages

| Package | CLI | Purpose |
|---|---|---|
| [`config_only`](src/config_only/README.md) | `apprc-config-only` | Configuration without a storage root. |
| [`config_with_storage`](src/config_with_storage/README.md) | `apprc-config-with-storage` | Configuration with one selected storage root. |
| [`explicit_env_precedence`](src/explicit_env_precedence/README.md) | `apprc-explicit-env-precedence` | Shell versus explicit env-file selector precedence. |
| [`cli_runtime`](src/cli_runtime/README.md) | `apprc-cli-runtime` | App-owned Typer callback integrated with `CliRuntime`. |
| [`_example_apps_utils`](src/_example_apps_utils/README.md) | `apprc-examples-run-all` | Internal registry and runner support. |

Each runnable app owns a `config/` package with `__init__.pyi`,
`_facade.py`, `app.py`, `sections/`, `bundle.py`, `catalog.py`, and
`config/apprc.defaults.env`.

## Docs

- [Development example app guide](../../docs/Development.md#example-apps)
- [Configuration file reference](../../docs/References.md#configuration-files)
- [System model](../../docs/Explanations.md#system-model)
