# AppRC How-To Guides

## Table of contents

1. [Choose a recipe](#1-choose-a-recipe)
2. [Integrate AppRC](#2-integrate-apprc)
3. [Set up storage](#3-set-up-storage)
4. [Edit config and storages](#4-edit-config-and-storages)
5. [Migrate from 0.19](#5-migrate-from-019)
6. [Troubleshoot `config doctor`](#troubleshoot-config-doctor)

## 1. Choose a recipe

AppRC always provides typed config and optional per-user app overrides. Add
`rc.Storage()` only when the application needs a persistent data directory.

| Application | Declaration | First-run requirement |
| --- | --- | --- |
| Config only | `rc.AppRC(...)` | None |
| Config and persistent data | `rc.AppRC(..., storage=rc.Storage())` | Create or select one storage directory |

See [References](References.md) for exact arguments and
[Explanations](Explanations.md) for the design.

## 2. Integrate AppRC

Install the runtime and optional editor:

```bash
python -m pip install apprc
python -m pip install "apprc[tui]"
```

Generate the recommended package layout:

```bash
apprc scaffold config \
  --package myapp \
  --app-name myapp \
  --display-name "My App" \
  --storage \
  --target src
```

Omit `--storage` for a config-only application. AppRC derives the selector
name `MYAPP_STORAGE`; pass `--storage-selector-env-key` only to override it.

The essential declaration is small:

```python
from pathlib import Path

import apprc as rc


MyRC = rc.AppRC(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    storage=rc.Storage(),
)


@MyRC.config("app", prefix="MYAPP_", title="App")
class AppSettings(rc.Config):
    storage_root: Path = rc.field(
        "MYAPP_STORAGE",
        editable=False,
        required=True,
    )
    profile: str = rc.field("MYAPP_PROFILE", default="default")
    token: str = rc.field("MYAPP_TOKEN", required=True, secret=True)


@MyRC.bundle
class MyAppConfig:
    app: AppSettings
```

Put non-secret defaults in `myapp/config/apprc.defaults.env`:

```dotenv
MYAPP_PROFILE="default"
```

Mount the generated commands before runtime config objects are constructed:

```python
import typer

from myapp.config import MyAppConfig, MyRC


app = typer.Typer()
MyRC.mount_cli(app)


@app.command()
def run() -> None:
    cfg = MyAppConfig()
    typer.echo(cfg.app.profile)
```

For a non-Typer application entrypoint, call `MyRC.bootstrap()` before
constructing the bundle when AppRC should load managed dotenv files:

```python
MyRC.bootstrap()
config = MyAppConfig()
run_application(config)
```

Pass that config object through the runtime instead of asking lower-level
workspace or service constructors to bootstrap again. Direct construction is
also valid when a test or caller intentionally uses only Python values and the
current process environment:

```python
config = MyAppConfig()
```

A high-level convenience client may use the parameterless one-time helper when
the default bootstrap policy is always correct:

```python
MyRC.ensure_bootstrapped()
config = MyAppConfig()
```

Do not use `ensure_bootstrapped()` when the caller needs custom env files,
precedence, or storage selection. Call `bootstrap(...)` with those choices at
the application entrypoint instead.

## 3. Set up storage

Storage apps have three setup routes.

To keep shell path completion, provide custom paths as an option:

```bash
myapp config setup --storage-root /absolute/path/to/storage
```

To accept the platform data directory without a prompt:

```bash
myapp config setup --yes
```

On an interactive terminal, the first runtime command can offer the same
suggested directory when `prompt_on_first_run=True`, which is the default.

Setup creates the directory and `apprc.storage.env`, then saves its absolute
path under `MYAPP_STORAGE` in `apprc.app.env`. No shell export is required.
It keeps the existing next-step output and points users to `config doctor`.

Use a different suggested path or disable the first-run prompt in the
declaration:

```python
MyRC = rc.AppRC(
    app_name="myapp",
    config_package="myapp.config",
    storage=rc.Storage(
        suggested_root=Path.home() / "Projects" / "myapp-data",
        prompt_on_first_run=False,
    ),
)
```

## 4. Edit config and storages

The app scope is always available. Its file is created only when a command or
editor save needs it.

```bash
myapp config set MYAPP_PROFILE development --scope app
myapp config app init
myapp config edit
```

For a storage app, `config edit` always shows `Setup`, `New`, `Register`,
`Rename`, `Location`, `Move`, `Archive`, and `Delete` as applicable to the
current selection. An empty `apprc.toml` is not a prerequisite: `New` and
`Register` can create the first named storage.

The equivalent basic CLI operations are:

```bash
myapp config storage add project-a /data/project-a
myapp config storage list
myapp config storage remove project-a
```

Opening the editor, running `paths`, and running `doctor` do not create files.

## 5. Migrate from 0.19

First update the application declaration from a capability constructor to
`rc.AppRC(...)` with optional `rc.Storage()`.

Then inspect all app, TOML, active-storage, and registered-storage moves:

```bash
myapp config migrate --dry-run
myapp config migrate --yes
```

The migration uses these names:

| 0.19 | 0.20 |
| --- | --- |
| `.env.shared` | `apprc.defaults.env` |
| `.env.apprc-app` | `apprc.app.env` |
| `.env.apprc-storage` | `apprc.storage.env` |
| `<app>.apprc.toml` | `apprc.toml` |

Rename the packaged defaults file in the application source manually; the
runtime command does not modify installed package files.

AppRC 0.20 reads a legacy file when the current file is absent. If both exist,
the current file wins and AppRC warns instead of merging. `config migrate`
preflights every target and stops before writing when it finds a conflict. It
moves files and is safe to rerun after a partial filesystem failure.

Custom filename overrides and an explicit `<APP>_APPRC_TOML` location are not
automatic migration targets.

> [!WARNING]
> The four 0.19 capability constructors are deprecated in 0.20 and will be
> removed in 0.21.

## Troubleshoot `config doctor`

Start with read-only state:

```bash
myapp config paths
myapp config doctor
myapp config doctor --json
```

| Status | Meaning | Next action |
| --- | --- | --- |
| `runnable` | Required config and selected storage are usable. | Run the application. |
| `env_not_set` | A storage app has no selector. | Run `config setup`. |
| `storage_not_ready` | The selected root or its config file is missing or invalid. | Correct the path or rerun setup. |
| `app_config_not_ready` | A required legacy app file is missing or unreadable. | Run setup or fix permissions. |
| `named_storage_not_ready` | `apprc.toml` cannot be read. | Fix the file or select a direct path. |

The JSON payload uses the 0.20 vocabulary, including `storage_enabled`,
`app_env`, `storage_selector_env_key`, and `apprc_toml`.
