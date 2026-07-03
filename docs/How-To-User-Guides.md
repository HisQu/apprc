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

Install the optional Textual editor when you want generated `config edit`
commands:

```bash
python -m pip install "apprc[tui]"
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

Create a config package in the app and declare one AppRC facade plus one or
more registered config classes. The recommended layout is:

```text
myapp/config/
  __init__.py
  app.py
  sections/
    __init__.py
    app.py
  bundle.py
  catalog.py
```

Generate that layout when starting a new integration:

```bash
apprc scaffold config \
  --package myapp \
  --mode storage-only \
  --app-name myapp \
  --display-name "My App" \
  --storage-env-key MYAPP_STORAGE \
  --target src
```

The compact example below shows the same declarations in one file for reading.

All app-declared config areas belong under `config/sections/`. Keep small areas
as modules such as `sections/client.py`; use a nested package such as
`sections/rag/` when one area needs its own bundle, resources, or several leaf
settings. `config/bundle.py` should only assemble the app-level bundle, and
`config/catalog.py` should only expose metadata.

```python
from pathlib import Path

import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    storage_env_key="MYAPP_STORAGE",
)


@MyRC.config("app", prefix="MYAPP_", title="App")
class AppSettings(rc.Config):
    storage_root: Path = rc.field(
        "MYAPP_STORAGE",
        editable=False,
        required=True,
        title="Storage root",
        description="Active storage root.",
    )
    profile: str = rc.field(
        "MYAPP_PROFILE",
        default="default",
        title="Profile",
        description="Named runtime profile.",
    )
    access_token: str = rc.field(
        "MYAPP_ACCESS_TOKEN",
        required=True,
        secret=True,
        title="Access token",
        description="Secret service token.",
    )


@MyRC.config("resources", title="Resources")
class PackageResources(rc.ConfigBase):
    package: str = "myapp.resources"


@MyRC.bundle
class MyAppConfig:
    app: AppSettings
    resources: PackageResources
```

Put packaged defaults in the same config package:

```dotenv
MYAPP_PROFILE="default"
```

Save that file as `.env.shared`. Do not put secrets in packaged defaults.

> [!IMPORTANT]
> Register config classes with `@MyRC.config(...)` before constructing them.
> The registration metadata drives validation, generated CLI output, editor
> rows, and provenance.

<br>

<!-- ======================================================== -->

<br>

## Choose A Capability Constructor
<!-- ======================================================== -->

Create one `rc.AppRC` facade for the app:

```python
import apprc as rc


MyRC = rc.AppRC.storage_only(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    storage_env_key="MYAPP_STORAGE",
)
```

Choose the constructor by persistence needs:

| Use Case | Constructor |
|---|---|
| Shell env and explicit env files are enough | `rc.AppRC.env_only(...)` |
| App needs one active storage root | `rc.AppRC.storage_only(...)` |
| App needs per-user config but no storage root | `rc.AppRC.app_wide_config(...)` |
| App needs per-user config and storage roots | `rc.AppRC.app_wide_storage(...)` |

Storage-capable constructors require an explicit `storage_env_key` when the app
needs a storage selector such as `MYAPP_STORAGE`.

<br>

<!-- ======================================================== -->

<br>

## Bootstrap A Typer App
<!-- ======================================================== -->

Call AppRC bootstrap before commands construct `rc.Config` objects. Mount the
generated `config` command group below the app.

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

`MyRC.mount_cli(...)` registers the standard AppRC CLI runtime options:
`--env-file`, `--env-file-overrides-os-environ`, `--skip-dotenv-layers`,
`--storage`, and `--log-level`. It also lets setup and inspection commands run
before required runtime settings exist.

Apps that own their Typer callback and extra options can use
`rc.cli.CliRuntime`. The runtime keeps AppRC's deterministic config CLI behavior
in AppRC, while the app still builds its own runtime state.

```python
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import Annotated

import typer

import apprc as rc

from myapp.config import MyRC


@dataclass(frozen=True, slots=True)
class MyCliOptions:
    env_files: Sequence[Path] | None = None
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    storage: str | None = None
    log_level: str | None = None
    workdir: Path | None = None


@dataclass(slots=True)
class MyCliState(rc.cli.DefaultConfigCliState):
    workdir: Path | None


def build_state(
    context: rc.cli.CliRuntimeContext,
    options: MyCliOptions,
) -> MyCliState:
    return MyCliState(
        env_bootstrap=context.env_bootstrap,
        storage=options.storage,
        workdir=options.workdir,
    )


app = typer.Typer()
runtime = rc.cli.CliRuntime(
    MyRC.kit,
    state_type=MyCliState,
    state_factory=build_state,
    runtime_policy=rc.cli.CliRuntimePolicy(
        runtime_independent_commands={
            "tool": rc.cli.RuntimeIndependentCommand(skip_empty=True),
            "llm": rc.cli.RuntimeIndependentCommand(
                skip_empty=True,
                action_prefixes={("benchmark",)},
            ),
            "rag": rc.cli.RuntimeIndependentCommand(
                skip_empty=True,
                action_prefixes={("cache",), ("benchmark",)},
            ),
        },
        extra_cli_value_options={"--workdir"},
    ),
)
runtime.mount_config_group(app)


@app.callback()
def cli(
    ctx: typer.Context,
    env_files: rc.cli.EnvFilesOption = None,
    env_file_overrides_os_environ: rc.cli.EnvFileOverridesOption = False,
    skip_dotenv_layers: rc.cli.SkipDotenvLayersOption = False,
    storage: rc.cli.StorageOption = None,
    log_level: rc.cli.LogLevelOption = None,
    workdir: Annotated[Path | None, typer.Option("--workdir")] = None,
) -> None:
    options = MyCliOptions(
        env_files=env_files,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        load_dotenv_layers=not skip_dotenv_layers,
        storage=storage,
        log_level=log_level,
        workdir=workdir,
    )
    session = runtime.prepare(ctx, options)
    if session.runtime_setup_skipped:
        return
```

`extra_cli_flag_options` and `extra_cli_value_options` are additions to
AppRC's standard CLI runtime options, so custom callbacks only list app-specific
option names. `RuntimeIndependentCommand(skip_help=True)` is the default, which lets
declared command-group help such as `tool --help` render before runtime storage
or required settings exist. Use `exact_actions` for complete action paths and
`action_prefixes` for subtrees whose child commands have their own options. On
skipped runs, `session.state` is `None`; AppRC still stores its bootstrap context
for generated config commands. Runtimeful generated config commands require the
app callback to leave the declared `state_type` on `ctx.obj`; runtime-independent
generated config commands use AppRC's stored context instead.
Runtime-independent app commands can read the original app option object with
`rc.cli.cli_options_from(ctx, MyCliOptions)` even when runtime setup was skipped.
Nested in-process CLIs can call `runtime.run_forwarded(child_app, args=..., prog_name=...)`
so the child runtime policy inspects the forwarded child arguments.

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
