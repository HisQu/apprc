# AppRC: Application Runtime Config

[![CI](https://github.com/HisQu/apprc/actions/workflows/ci.yml/badge.svg)](https://github.com/HisQu/apprc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/apprc)](https://pypi.org/project/apprc/)
[![Python](https://img.shields.io/pypi/pyversions/apprc)](https://pypi.org/project/apprc/)
[![License](https://img.shields.io/pypi/l/apprc)](LICENSE)

AppRC gives Python applications typed settings, source provenance, persistent
user overrides, and named storage directories. Declare the settings once, resolve
the inputs for each run, and use the same declaration for setup and editing.

- [Install](#install)
- [Load settings](#load-settings)
- [Save user settings](#save-user-settings)
- [Add named storage](#add-named-storage)
- [Add terminal commands](#add-terminal-commands)
- [Examples and documentation](#examples-and-documentation)

## Install

Python 3.12 or newer is required.

| Command | Includes |
| --- | --- |
| `python -m pip install apprc` | Configuration, Typer commands, prompts, and the Textual editor |
| `python -m pip install apprc-core` | Configuration and noninteractive management, without terminal dependencies |

Both installations use `import apprc`. The `apprc` distribution depends on the
exact matching `apprc-core` version and installs the `apprc` command.

**Warning**

When upgrading from the previous single-distribution release, use a fresh
environment or uninstall the old `apprc` first. See the
[migration guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#migrate-existing-applications).
The refactor is currently unreleased.

## Load settings

```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("app", prefix="DEMO_")
class Settings(rc.Config):
    retries: int = rc.field("DEMO_RETRIES", default=3)
    verbose: bool = rc.field("DEMO_VERBOSE", default=False)

resolved = MyRC.resolve(environment={"DEMO_RETRIES": "5"})
settings = resolved.build(Settings)
assert settings.retries == 5
```

Omit `environment` to capture the current process environment. Pass `{}` to
exclude it. Resolution reads files without creating them and never changes
`os.environ`. A resolution retains its own values and provenance even when
another run chooses different inputs.

Constructor overrides remain ordinary Python values:

```python
settings = resolved.build(Settings, retries=8)
assert settings.retries == 8
```

For explicit dotenv inputs, use
`MyRC.resolve(rc.ResolveOptions(env_files=(path,)))`, where `path` is a
`pathlib.Path`. See [source precedence](https://github.com/HisQu/apprc/blob/main/docs/References.md#source-precedence).

## Save user settings

Enable the user dotenv when declaring the application:

```python
MyRC = rc.AppRC(app_id="demo", user_dotenv=rc.UserDotenv())
```

Register your settings on that declaration, then create the file explicitly:

```python
manager = MyRC.manage()
manager.setup()
plan = manager.plan_update("app.retries", "6", scope="user")
manager.apply_edit(plan)
settings = manager.resolve().build(Settings)
```

The fixed filename is `apprc.user.env`. Its default directory is
`~/.local/share/demo`; `DEMO_APPRC_DIR` relocates it. Missing user overrides are
allowed. Required fields are checked when constructing settings.

Inspection and edit planning do not write. Applying an edit checks that the
file has not changed since planning. See
[editing and conflicts](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#edit-saved-values).

## Add named storage

Use storage when the application has persistent data directories:

```python
from pathlib import Path

MyRC = rc.AppRC(app_id="demo", storage=rc.Storage())
manager = MyRC.manage()
manager.setup(storage_root=Path("./demo-data"), storage_name="local")
resolved = MyRC.resolve(rc.ResolveOptions(storage="local", storage_required=True))
```

A storage has an `apprc.storage.env` file. The `apprc.toml` registry records names,
roots, and the default selection. `UserDotenv()` and `Storage()` are independent
capabilities; either or both may be enabled.

Storage is optional for a run unless `ResolveOptions(storage_required=True)`
is passed. A supplied invalid selector still fails. See
[storage selection](https://github.com/HisQu/apprc/blob/main/docs/References.md#storage-selection) and
[storage operations](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#manage-storage).

## Add terminal commands

Install `apprc`, then mount its commands on a Typer app:

```python
import typer

app = typer.Typer()
rc.cli.mount_config_cli(app, MyRC)

@app.command()
def run(ctx: typer.Context) -> None:
    state = rc.cli.state_from(ctx, rc.cli.DefaultConfigCliState)
    assert state.resolved is not None
    settings = state.resolved.build(Settings)
    typer.echo(settings.retries)
```

The application gets `config paths`, `config doctor`, `config setup`,
`config set`, and `config edit`, plus storage commands when declared.
Use `storage_required=True` on `mount_config_cli` if its runtime commands need
storage. For an app-owned callback, use `rc.cli.CliRuntime` instead.

Textual classes live under `rc.tui`. The future Toga interface and cx_Freeze
build tooling are separate planned integrations; neither is implemented here.

## Examples and documentation

- [Manual](https://github.com/HisQu/apprc/blob/main/docs/README.md): choose a task or look up an exact API.
- [Integration and migration](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md): setup, bundles, terminal
  state, reloads, and upgrading existing code.
- [Reference](https://github.com/HisQu/apprc/blob/main/docs/References.md): supported names, files, precedence, and commands.
- [Architecture](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md): ownership and why loading stays explicit.
- [Development](https://github.com/HisQu/apprc/blob/main/docs/Development.md): both distributions, checks, and releases.
- [Runnable examples](https://github.com/HisQu/apprc/blob/main/examples/example_apps/README.md): six small applications
  and a manual lab.
