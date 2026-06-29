<!-- ======================================================== -->

<br>

## Table Of Contents
<!-- ======================================================== -->

1. [How-To User Guides](#1-how-to-user-guides)
   1. [Recipe Map](#recipe-map)
2. [Integrate AppRC](#2-integrate-apprc)
   1. [Install AppRC](#install-apprc)
   2. [Declare Typed Config Fields](#declare-typed-config-fields)
   3. [Choose A Capability Constructor](#choose-a-capability-constructor)
   4. [Bootstrap A Typer App](#bootstrap-a-typer-app)
3. [Operate App Config](#3-operate-app-config)
   1. [Run First Storage Setup](#run-first-storage-setup)
   2. [Use App-Wide Config](#use-app-wide-config)
   3. [Manage Named Storages](#manage-named-storages)
   4. [Set And Edit Values](#set-and-edit-values)
   5. [Troubleshoot Config Doctor](#troubleshoot-config-doctor)
4. [Develop This Repository](#4-develop-this-repository)
   1. [Sync Dependencies](#sync-dependencies)
   2. [Run Verification](#run-verification)

<br>

# 1. How-To User Guides

<!-- ======================================================== -->

<br>

## Recipe Map
<!-- ======================================================== -->

Use this file when you want steps in order. Use
[References](References.md) when you need exact names and
[Explanations](Explanations.md) when you need the system model.

| Task | Recipe |
|---|---|
| Add AppRC to a Typer application | [Integrate AppRC](#2-integrate-apprc) |
| Initialize a storage-backed app | [Run First Storage Setup](#run-first-storage-setup) |
| Add per-user settings | [Use App-Wide Config](#use-app-wide-config) |
| Support named storage roots | [Manage Named Storages](#manage-named-storages) |
| Change one value | [Set And Edit Values](#set-and-edit-values) |
| Explain setup failures | [Troubleshoot Config Doctor](#troubleshoot-config-doctor) |

> [!NOTE]
> Related: use [Explanations: integration flow](Explanations.md#integration-flow)
> for the reasoning behind the recipe order.

<br>

# 2. Integrate AppRC

<!-- ======================================================== -->

<br>

## Install AppRC
<!-- ======================================================== -->

Install the runtime package:

```bash
python -m pip install apprc
```

Install the optional logging extra only when the host app calls
`setup_logging()`:

```bash
python -m pip install "apprc[logging]"
```

For editable local development of AppRC itself:

```bash
python -m pip install -e "." --group dev
```

> [!NOTE]
> Related: use [References: dependency surfaces](References.md#dependency-surfaces)
> for the difference between runtime dependencies, extras, and maintainer
> groups.

<br>

<!-- ======================================================== -->

<br>

## Declare Typed Config Fields
<!-- ======================================================== -->

Create a config package in the host app, usually `<app>/config/__init__.py`,
and declare one or more `EnvConfig` classes.

```python
from pathlib import Path

from apprc import EnvConfig, env_field, env_owner


@env_owner(
    key="app",
    title="App",
    env_prefix="MYAPP_",
    rc_path=("app",),
)
class MyAppEnv(EnvConfig):
    storage_root: Path = env_field(
        "STORAGE",
        editable=False,
        required=True,
        title="Storage root",
        explanation_short="Active storage root.",
    )
    profile: str = env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named runtime profile.",
    )
    access_token: str = env_field(
        "ACCESS_TOKEN",
        required=True,
        secret=True,
        title="Access token",
        explanation_short="Secret service token.",
    )
```

Put packaged defaults in the same config package:

```dotenv
MYAPP_PROFILE="default"
```

Save that file as `.env.shared`. Do not put secrets in packaged defaults.

> [!IMPORTANT]
> Add fields to the AppRC owner before reading them from application code. The
> owner metadata drives validation, generated CLI output, editor rows, and
> provenance.

<br>

<!-- ======================================================== -->

<br>

## Choose A Capability Constructor
<!-- ======================================================== -->

Create one `AppConfigKit` for the host app:

```python
from apprc import AppConfigKit

from myapp.config import MyAppEnv


APP_CONFIG = AppConfigKit.storage_only(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    envs=(MyAppEnv,),
)
```

Choose the constructor by persistence needs:

| Use Case | Constructor |
|---|---|
| Shell env and explicit env files are enough | `AppConfigKit.env_only(...)` |
| App needs one active storage root | `AppConfigKit.storage_only(...)` |
| App needs per-user config but no storage root | `AppConfigKit.app_wide_config(...)` |
| App needs per-user config and storage roots | `AppConfigKit.app_wide_storage(...)` |

Storage-capable constructors derive `<APP>_STORAGE` unless
`storage_env_key="MYAPP_STORAGE"` is passed.

<br>

<!-- ======================================================== -->

<br>

## Bootstrap A Typer App
<!-- ======================================================== -->

Call AppRC bootstrap before commands construct `EnvConfig` objects. Mount the
generated `config` command group below the host app.

```python
import typer

from apprc.cli import mount_config_cli

from myapp.config import APP_CONFIG, MyAppEnv

app = typer.Typer()
mount_config_cli(app, APP_CONFIG)


@app.command()
def run() -> None:
    cfg = MyAppEnv()
    typer.echo(cfg.profile)
```

`mount_config_cli(...)` registers the standard AppRC root options:
`--env-file`, `--env-file-overrides-os-environ`, `--skip-dotenv-layers`,
`--storage`, and `--log-level`. It also lets setup and inspection commands run
before required runtime settings exist. Pass `state_factory=...` when the app
needs custom root state after bootstrap, and `args_provider=...` when a wrapper
or test harness needs to provide command tokens explicitly.

Apps that already have a root callback can use `CliBootstrapOptions`,
`prepare_typer_context(...)`, and `APP_CONFIG.typer_app(...)` directly instead
of the mount helper.

> [!NOTE]
> Related: use [References: generated CLI commands](References.md#generated-cli-commands)
> for every generated command.

<br>

# 3. Operate App Config

<!-- ======================================================== -->

<br>

## Run First Storage Setup
<!-- ======================================================== -->

For `storage_only(...)` and `app_wide_storage(...)` apps, create a first
storage root explicitly:

```bash
myapp config paths
myapp config setup --yes --storage-root /absolute/path/to/storage
export MYAPP_STORAGE="/absolute/path/to/storage"
myapp config doctor
```

Expected results:

- `config paths` reports `writes: none`.
- `config setup` creates `<storage-root>/.env.apprc-storage`.
- `app_wide_storage(...)` also creates `.env.apprc-app`.
- `config doctor` reports `runnable` once required files and selectors exist.

> [!IMPORTANT]
> `MYAPP_STORAGE` selects storage. It can be a path selector or, when a
> named-storage index exists, a registered storage name.

<br>

<!-- ======================================================== -->

<br>

## Use App-Wide Config
<!-- ======================================================== -->

Enable app-wide config explicitly for optional app-wide layers:

```bash
myapp config app init
myapp config set profile work --scope app
myapp config doctor
```

Use app-wide config for values that apply across storage roots or for apps
that do not use storage. Use storage config for values that should travel with
one storage root.

When app-wide and storage scopes are both writable, pass `--scope app` or
`--scope storage` so AppRC does not guess.

<br>

<!-- ======================================================== -->

<br>

## Manage Named Storages
<!-- ======================================================== -->

Named storage is optional for storage-capable apps. Add names when users need
short selectors instead of full paths:

```bash
myapp config storage add alpha /absolute/path/to/alpha
myapp config storage add beta /absolute/path/to/beta
myapp config storage list
export MYAPP_STORAGE="alpha"
myapp config doctor
```

Remove a registry entry without deleting the storage directory:

```bash
myapp config storage remove alpha
```

Relocate the named-storage index only when needed:

```bash
export MYAPP_APPRC_TOML="/absolute/path/to/myapp.apprc.toml"
```

`MYAPP_APPRC_TOML` changes where AppRC reads and writes the index. It is not
the active storage selector.

<br>

<!-- ======================================================== -->

<br>

## Set And Edit Values
<!-- ======================================================== -->

Set values by env key, dotted config path, or unique field name:

```bash
myapp config set MYAPP_PROFILE work --scope storage
myapp config set app.profile work --scope app
myapp config set profile work --scope storage
```

Open the Textual editor:

```bash
myapp config edit
```

The editor shows `Effective`, `Shell`, `App-wide`, `Storage`, `Default`, and
`Explanation` columns. It opens without creating files. Saving creates only
the chosen app-wide or storage dotenv file.

Secret fields are redacted in displays. Read-only fields, such as storage
selector fields marked `editable=False`, cannot be written through AppRC
dotenv editors.

<br>

<!-- ======================================================== -->

<br>

## Troubleshoot Config Doctor
<!-- ======================================================== -->

Start with machine-readable output when a setup is unclear:

```bash
myapp config doctor --json
```

Common statuses:

| Status | Meaning | First Fix |
|---|---|---|
| `env_not_set` | A required selector such as `MYAPP_STORAGE` is missing. | Export the selector or pass `--storage`. |
| `storage_not_ready` | The selected root or storage dotenv is missing. | Run `config setup --storage-root ...`. |
| `app_config_not_ready` | A default app-wide layer is expected but missing. | Run `config app init`. |
| `named_storage_not_ready` | The named-storage index is missing, unreadable, or invalid for the selector. | Fix the index or add storage again. |
| `runnable` | Runtime config can load. | No fix needed. |

Use `config paths --json` when you want the same path and capability report
without treating non-runnable state as a command failure.

<br>

# 4. Develop This Repository

<!-- ======================================================== -->

<br>

## Sync Dependencies
<!-- ======================================================== -->

Use the locked maintainer environment:

```bash
just sync
```

Plain `pip` also works:

```bash
python -m pip install -e "." --group dev
```

<br>

<!-- ======================================================== -->

<br>

## Run Verification
<!-- ======================================================== -->

For docs-only changes:

```bash
python src/apprc_dev/packaging/pypi_readme.py
.venv/bin/pytest tests/test_pypi_readme.py
git diff --check
```

For code changes:

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
```

> [!NOTE]
> Related: use [Development: verification](Development.md#4-verification) for
> the maintainer checklist.
