# `apprc`: Application Runtime Config

`apprc` is a runtime configuration toolkit for Python applications. You
declare typed config sections once, choose which persistence layers your app
supports, and AppRC gives you deterministic dotenv loading, storage-root
selection, zero-write diagnostics, generated Typer `config` commands, a
Textual editor, and optional structured logging helpers.

Runtime reads are side-effect free. Files are created only by explicit setup,
storage, or save commands.

## Table Of Contents

1. [Installation](#installation)
2. [Quickstart](#quickstart)
3. [Mental Model](#mental-model)
4. [Generated Config CLI](#generated-config-cli)
5. [Runtime Precedence](#runtime-precedence)
6. [Optional Logging](#optional-logging)
7. [Detailed Documentation](#detailed-documentation)
8. [Development](#development)

## Installation

```shell
python -m pip install apprc
```

Install optional structured logging support when your app calls
`setup_logging()`:

```shell
python -m pip install "apprc[logging]"
```

AppRC supports Python 3.12 and newer.

## Quickstart

Declare typed config sections with `EnvConfig`, `@env_owner`, and
`env_field(...)`:

```python
from pathlib import Path

from apprc import AppConfigKit, EnvConfig, env_field, env_owner


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
    )


APP_CONFIG = AppConfigKit.storage_only(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    envs=(MyAppEnv,),
)
```

Add packaged defaults in `myapp/config/.env.shared`:

```dotenv
MYAPP_PROFILE="default"
```

Bootstrap your app before constructing runtime config objects:

```python
from pathlib import Path
from typing import Annotated

import typer

from apprc.cli import bootstrap_cli_env, config_request_skips_runtime_bootstrap

from myapp.config import APP_CONFIG, MyAppEnv

app = typer.Typer()


class CliState:
    env_bootstrap = None
    storage: str | None = None


@app.callback()
def root_cmd(
    ctx: typer.Context,
    env_files: Annotated[list[Path] | None, typer.Option("--env-file")] = None,
    env_file_overrides_os_environ: Annotated[
        bool,
        typer.Option("--env-file-overrides-os-environ"),
    ] = False,
    storage: Annotated[str | None, typer.Option("--storage")] = None,
) -> None:
    state = CliState()
    state.storage = storage
    ctx.obj = state
    if config_request_skips_runtime_bootstrap("config"):
        return
    state.env_bootstrap = bootstrap_cli_env(
        APP_CONFIG,
        env_files=tuple(env_files or ()),
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        load_dotenv_layers=True,
        storage=storage,
    )


@app.command()
def run() -> None:
    cfg = MyAppEnv()
    typer.echo(f"profile={cfg.profile}")


app.add_typer(APP_CONFIG.typer_app(state_type=CliState), name="config")
```

Then initialize a storage-backed app:

```shell
myapp config paths
myapp config setup --yes --storage-root /absolute/path/to/storage
export MYAPP_STORAGE="/absolute/path/to/storage"
myapp config doctor
myapp config set access_token secret-value --scope storage
myapp run
```

## Mental Model

AppRC has one contract and several workflows built from it.

| Concept | Meaning |
| --- | --- |
| Config field | One typed setting declared with `env_field(...)`. |
| Config owner | A related group of fields declared by `@env_owner(...)`. |
| App config kit | The app-level contract that selects supported persistence layers. |
| Bootstrap | A startup step that merges dotenv layers into this Python process. |
| Generated CLI | A reusable Typer `config` command group for inspection and edits. |
| Editor | A Textual view over the same owners, fields, and dotenv layers. |

Choose one capability constructor:

| Constructor | Storage root | App-wide dotenv | Named storage index |
| --- | --- | --- | --- |
| `AppConfigKit.env_only(...)` | disabled | optional | disabled |
| `AppConfigKit.storage_only(...)` | required | optional | optional |
| `AppConfigKit.app_wide_config(...)` | disabled | default | disabled |
| `AppConfigKit.app_wide_storage(...)` | required | default | optional |

AppRC-managed persistence files are explicit:

| Layer | Default location | Created by |
| --- | --- | --- |
| Packaged shared defaults | package `.env.shared` | the application package |
| App-wide config | platform config home `.env.apprc-app` | `config app init`, app-wide setup, or app-scope save |
| Storage config | `<storage-root>/.env.apprc-storage` | storage setup, `config storage add`, or storage-scope save |
| Named-storage index | `<config-home>/<app>.apprc.toml` | `config storage add/remove` |

**Important**

Runtime reads and diagnostics do not create files. `bootstrap`, `config
paths`, `config doctor`, and opening `config edit` are zero-write.

## Generated Config CLI

Mounting `APP_CONFIG.typer_app(...)` gives your app these commands:

```shell
myapp config paths
myapp config doctor
myapp config show
myapp config setup
myapp config set KEY VALUE --scope app
myapp config set KEY VALUE --scope storage
myapp config edit
myapp config app init
myapp config storage add NAME PATH
myapp config storage list
myapp config storage remove NAME
```

The command group follows the selected capabilities. For example, storage-free
apps do not expose named-storage commands.

Use `config paths` before setup to see candidate paths and declared
capabilities without writing anything. Use `config doctor` when a machine is
not runnable; it reports a status such as `env_not_set`, `storage_not_ready`,
`app_config_not_ready`, `named_storage_not_ready`, or `runnable`.

## Runtime Precedence

When dotenv layers are loaded, AppRC merges values in this order:

1. packaged `.env.shared`
2. app-wide `.env.apprc-app`, when allowed and present
3. selected storage `.env.apprc-storage`, when storage is selected and present
4. explicit `--env-file` values
5. existing `os.environ`

With `--env-file-overrides-os-environ`, explicit env files move after
`os.environ` and win over shell exports.

Storage selector resolution uses:

1. root `--storage`
2. shell env, for example `MYAPP_STORAGE`
3. explicit env files, respecting `--env-file-overrides-os-environ`
4. app-wide `.env.apprc-app`, when active
5. packaged `.env.shared`

Path selectors work without a named-storage index. Bare named selectors use
`<app>.apprc.toml` when the index exists.

## Optional Logging

AppRC also includes stdlib-compatible semantic logging helpers. The base
logger API imports without `structlog`; `setup_logging()` requires the
`logging` extra.

```python
from apprc.logging import get_logger, setup_logging

setup_logging(level="INFO", renderer="cli")
log = get_logger(__name__)
log.success("configured", extra_struct={"profile": "default"})
```

Create application loggers with `get_logger(name)` or call
`install_app_logger_class()` before other code creates those names with
`logging.getLogger(name)`. Existing plain stdlib logger instances cannot be
safely reclassed, so `get_logger(name)` raises `RuntimeError` for those names.

## Detailed Documentation

The root README is the short adopter path. The detailed manual lives in
[docs](docs/README.md):

- [How-To User Guides](docs/How-To-User-Guides.md) for integration recipes.
- [Explanations](docs/Explanations.md) for the AppRC system model.
- [References](docs/References.md) for exact commands, files, and APIs.
- [Development](docs/Development.md) for maintainer workflow and docs rules.

The repository also ships a runnable example app in
[examples/apprc_example_app](examples/apprc_example_app).

## Development

```shell
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
```

Regenerate the PyPI README after editing this file:

```shell
python src/apprc_dev/packaging/pypi_readme.py
```
