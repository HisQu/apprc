<!-- ============================================================== -->
<!-- == Header ==================================================== -->
<div align="center">

# `apprc`: Application Runtime Config

*Part of:*

<a href="https://hisqu.de" target="_blank">
  <img
  src="https://avatars.githubusercontent.com/u/196629600?s=200&v=4"
  width="100px" alt="logo"
  style="margin-top: -10px;">
</a>

<br>

[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pyright](https://img.shields.io/badge/type%20checked-pyright-blue)](https://microsoft.github.io/pyright/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC)](https://docs.pytest.org/)

</div>

[`direnv`]: https://direnv.net/
[`just`]: https://github.com/casey/just?tab=readme-ov-file#packages
[`uv`]: https://github.com/astral-sh/uv?tab=readme-ov-file#uv
[PEP 621]: https://peps.python.org/pep-0621/#packaging-type-information
[`typed-settings`]: https://typed-settings.readthedocs.io/
[`typer`]: https://typer.tiangolo.com/
[`python-dotenv`]: https://github.com/theskumar/python-dotenv
[`textual`]: https://github.com/Textualize/textual
[`structlog`]: https://github.com/hynek/structlog


`apprc` is a small Python library for application runtime configuration and
logging. It is useful when a project needs typed env-backed config, packaged
defaults, per-user storage registries, local override files, a reusable
`config` CLI, a terminal config editor, and structured logs without rebuilding
that plumbing in every application.

The key idea: the application declares its config contract once, and `apprc`
derives the boring workflows from that contract.

### Tech Stack:
- [`typed-settings`] for typed config fields and runtime dataclasses.
- [`typer`] for CLI commands.
- [`python-dotenv`] for `.env` file parsing and writing.
- [`textual`] for the terminal config editor.
- [`structlog`] for structured logging.

<br>

# Installation

> [!IMPORTANT]
> ### Prerequisites
> - Python >=3.12
> - `git`
> - Optional: [`uv`], [`just`], [`direnv`]

<br>

### Install From PyPI

```shell
python -m pip install apprc
```

<br>

### Use `apprc` As Project Dependency

Any Python build system supporting `pyproject.toml` ([PEP 621]) works.

For published releases, depend on the PyPI package:

```toml
[project]
dependencies = [
    "apprc",
]
```

For the current repository revision, depend on the Git URL:

```toml
[project]
dependencies = [
    "apprc @ git+https://github.com/HisQu/apprc.git",
]
```

<br>

### Editable Install With `pip`

```shell
git clone https://github.com/HisQu/apprc.git
cd apprc

python -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "." --group dev
```

<br>

### Editable Install With `uv`

```shell
git clone https://github.com/HisQu/apprc.git
cd apprc

uv sync --frozen --all-groups
```

<br>

### Verify

```shell
python -c "import apprc; print(apprc.AppConfigKit)"
pytest
```

<br>

# Example

An application usually wires AppRC in three steps: declare fields, create the
kit, and mount the generated `config` CLI.

```python
from dataclasses import dataclass

import typer

from apprc import AppConfigKit
from apprc.config import ConfigOwner, config_field

# 1) Declare the config fields your app owns.
CLIENT_OWNER = ConfigOwner(
    key="client",
    title="Client",
    env_prefix="MYAPP_",
    rc_path=("client",),
    runtime_cls=None,
    fields=(
        config_field(
            "model",
            "MODEL",
            str,
            default="demo-model",
            title="Model",
            explanation="Model used by client calls.",
        ),
    ),
)

# 2) Create the reusable AppRC facade for your application.
MYAPP_CONFIG = AppConfigKit(
    app_name="myapp",
    display_name="MyApp",
    config_package="myapp.config",
    owners=(CLIENT_OWNER,),
    storage_root_env_key="MYAPP_D_STORAGE",
    registry_filename="myapp.toml",
    shared_env_filename=".env.shared",
    local_env_filename=".env.local",
)

# 3) Mount the generated `myapp config ...` command group.
@dataclass(slots=True)
class CliState:
    env_bootstrap: object | None = None
    storage: str | None = None


app = typer.Typer()
app.add_typer(
    MYAPP_CONFIG.typer_app(state_type=CliState),
    name="config",
)
```

Runtime dataclasses can inherit `BaseEnv` when you want typed objects populated
from the bootstrapped environment. The important first step is the owner
inventory: AppRC reuses it for loading, validation, docs, CLI commands, and the
terminal editor.

AppRC does not install its own `apprc` command. The config CLI is meant to be
mounted as a subcommand of the application that depends on AppRC.

Users then get:

```shell
myapp config init /absolute/path/to/storage --name default --default
myapp config doctor
myapp config show --json
myapp config set client.model other-model
myapp config edit
```

<br>

# Explanations

### Config Model

`apprc` separates config into clear layers:

| Layer | Owner | Purpose |
|---|---|---|
| `ConfigField` | application | One typed env-backed setting. |
| `ConfigOwner` | application | A named section of related fields. |
| `.env.shared` | application package | Packaged defaults shipped with code. |
| `<storage>/.env.local` | user/project | Per-storage local overrides. |
| shell environment | user/process | Highest-priority process values by default. |
| `~/.config/<app>/<app>.toml` | AppRC registry | Named storage roots and default storage. |

Runtime dataclasses inherit `BaseEnv`. The dataclass owns Python attributes;
`ConfigOwner` owns env names, docs labels, editor labels, choices, and
redaction metadata.

### Bootstrap Precedence

Applications call `AppConfigKit.bootstrap(...)` once at CLI startup. It merges:

1. packaged `.env.shared`
2. selected storage-local `.env.local`
3. explicit `--env-file`
4. current shell environment

By default, the shell wins over `--env-file`. Set
`env_file_overrides_shell=True` when an explicit file should win inside the
current process.

### Storage Registries

Globally installed commands need to find user data without hardcoding one path.
`apprc` stores named roots in `~/.config/<app>/<registry_filename>`, for
example:

```toml
default_storage = "default"

[storages.default]
root = "/absolute/path/to/storage"
```

Each storage root owns its own local override file, such as `.env.local`.
On POSIX/WSL hosts, Windows drive paths such as `D:\Training\demo-project` are
normalized to usable local paths before AppRC writes the registry or reads a
storage-root environment value.

> [!IMPORTANT]
> POSIX shells consume unquoted backslashes before Python sees the argument.
> If you type `C:\Projects\demo-storage` without quotes, AppRC may receive
> `C:Projectsdemo-storage`, which is not recoverable as a real Windows path.
> Use one of these forms instead:
>
> ```shell
> myapp config init 'C:\Projects\demo-storage' --name default --default
> myapp config init C:/Projects/demo-storage --name default --default
> myapp config init /mnt/c/Projects/demo-storage --name default --default
> ```

### Logging

`apprc.logging` wraps stdlib logging and structlog. `setup_logging()` installs
formatters and dependency logger levels. `get_logger()` returns an `AppLogger`
with semantic helper methods such as `action_begin`, `success`, `retry`,
`fallback`, `telemetry`, and `traceback`.

Use AppRC logging when application logs should stay structured and readable in
CLI output, notebooks, and tests.

<br>

# Guides

### Define Config Fields

Put config declarations in your application package, usually
`myapp/config/owners.py`.

```python
from pathlib import Path

from apprc.config import CONFIG_MISSING, ConfigOwner, config_field

STORAGE_OWNER = ConfigOwner(
    key="storage",
    title="Storage",
    env_prefix="MYAPP_",
    rc_path=("storage",),
    runtime_cls=None,
    fields=(
        config_field(
            "root",
            "D_STORAGE",
            Path,
            default=CONFIG_MISSING,
            editable=False,
            required=True,
            explanation_short="Active storage root.",
            explanation_long="Selected through the AppRC storage registry.",
        ),
    ),
)
```

Use `editable=False` for values owned by the registry instead of `.env.local`.

### Bootstrap a CLI

Call bootstrap before creating runtime config objects.

```python
from apprc.cli import bootstrap_cli_env
from apprc.logging import setup_logging

state.env_bootstrap = bootstrap_cli_env(
    MYAPP_CONFIG,
    env_file=env_file,
    env_file_overrides_shell=env_file_overrides_shell,
    no_dotenv=no_dotenv,
    storage_name=storage,
    log_level=log_level,
    setup_logging=setup_logging,
)
```

### Add the Generated Config CLI

```python
config_app = MYAPP_CONFIG.typer_app(
    state_type=CliState,
    runtime_payload=lambda state: {
        "storage": str(state.env_bootstrap.storage_root)
        if state.env_bootstrap
        else None,
    },
)
app.add_typer(config_app, name="config")
```

### Edit Local Values in the Terminal

`config edit` opens a Textual editor. The editor shows:

- key number
- section
- env key
- shell status
- local value
- default value
- short explanation

Selecting a row opens a modal with type information, possible values, and the
long explanation. Secret values are redacted. Required missing values show
`<required>`.

### Use Logging

```python
from apprc.logging import get_logger, setup_logging

setup_logging(level="INFO", renderer="cli")
log = get_logger(__name__)

log.action_begin("Loading workspace")
log.success("Workspace ready", storage="default")
```

<br>

# References

### Important Modules

| Module | Look Here For |
|---|---|
| `apprc.config.schema` | `ConfigField`, `ConfigOwner`, field lookup, typed loading. |
| `apprc.config.kit` | `AppConfigKit`, the high-level app integration facade. |
| `apprc.config.environment` | CLI startup dotenv/bootstrap precedence. |
| `apprc.config.paths` | Storage-root path normalization helpers. |
| `apprc.config.storage_registry` | `~/.config/<app>/*.toml` storage names. |
| `apprc.config.local_env` | `<storage>/.env.local` reads, writes, validation. |
| `apprc.config.tui` | Textual app and modal interactions. |
| `apprc.config.tui_rendering` | Pure table cell rendering and styles. |
| `apprc.cli.config_app` | Generated `config` Typer commands. |
| `apprc.cli.bootstrap` | Common root CLI bootstrap options. |
| `apprc.logging` | Logging facade: `setup_logging`, `get_logger`, `AppLogger`. |

### Important Config Types

| Type | Meaning |
|---|---|
| `AppConfigKit` | Convenient object applications keep around. |
| `AppConfigSpec` | Frozen declaration behind the kit. |
| `ConfigOwner` | One config section, env prefix, runtime path, and fields. |
| `ConfigField` | One editable or read-only env-backed setting. |
| `BaseEnv` | Runtime dataclass base that binds values from env. |
| `EnvBootstrapResult` | Files and storage selected during CLI startup. |
| `StorageRegistry` | Parsed TOML registry. |
| `LocalEnvUpdate` | Result of writing one local dotenv override. |

### Config CLI Commands

| Command | Purpose |
|---|---|
| `config init STORAGE_ROOT --name NAME --default` | Register a storage root. |
| `config doctor` | Diagnose registry and selected storage state. |
| `config show --json` | Print resolved runtime config payload. |
| `config set-default NAME` | Change default storage. |
| `config set KEY VALUE` | Write one local override. |
| `config edit` | Open the Textual editor. |

### Logging Functions

| Function | Purpose |
|---|---|
| `setup_logging(...)` | Configure stdlib/structlog output. |
| `get_logger(__name__)` | Return an `AppLogger`. |
| `log.action_begin(...)` | Start a visible operation. |
| `log.success(...)` | Mark a completed operation. |
| `log.retry(...)` | Record retry attempts. |
| `log.fallback(...)` | Record fallback behavior. |
| `log.traceback(...)` | Emit exception information with redaction support. |
| `async_telemetry(...)` | Emit periodic async progress logs. |

<br>

# Development

### Local Setup

```shell
git clone https://github.com/HisQu/apprc.git
cd apprc

python -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "." --group dev
```

or:

```shell
uv sync --frozen --all-groups
```

### Quality Gates

Run these before sending changes:

```shell
ruff format .
ruff check .
pyright
pytest
```

### Test Against Haiu

Haiu is the main downstream integration test for AppRC. From the Haiu repo:

```shell
cd ../haiu
.venv/bin/python -m pip install --no-deps --no-build-isolation -e ../apprc
.venv/bin/pytest tests/haiu/core/test_config_tui.py -q
.venv/bin/pytest
```

Keep refactors behavior-preserving. If a cleanup would remove a public module,
change import-time side effects, or alter CLI output, treat that as a feature
change and ask first.
