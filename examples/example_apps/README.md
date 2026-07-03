# AppRC Example Apps

This directory is a dev-only editable package with runnable CLIs for each
AppRC capability mode.

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
| [`env_only`](src/env_only/README.md) | `apprc-env-only` | Env files and shell env only. |
| [`storage_only`](src/storage_only/README.md) | `apprc-storage-only` | Required active storage root. |
| [`app_wide_config`](src/app_wide_config/README.md) | `apprc-app-wide-config` | App-wide config without storage. |
| [`app_wide_storage`](src/app_wide_storage/README.md) | `apprc-app-wide-storage` | App-wide defaults plus storage-local values. |
| [`explicit_env_precedence`](src/explicit_env_precedence/README.md) | `apprc-explicit-env-precedence` | Shell versus explicit env-file selector precedence. |
| [`cli_runtime`](src/cli_runtime/README.md) | `apprc-cli-runtime` | App-owned Typer callback integrated with `CliRuntime`. |
| [`_example_apps_utils`](src/_example_apps_utils/README.md) | `apprc-examples-run-all` | Internal registry and runner support. |

Each runnable app owns a `config/` package with `__init__.pyi`,
`_facade.py`, `app.py`, `sections/`, `bundle.py`, `catalog.py`, and
`config/.env.shared`.

## Docs

- [Development example app guide](../../docs/Development.md#example-apps)
- [Repository path reference](../../docs/References.md#project-paths)
- [System model](../../docs/Explanations.md#package-architecture)
