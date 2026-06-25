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

**Important**

### Prerequisites
- Python >=3.12
- `git`
- Optional: [`uv`], [`just`], [`direnv`]

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

### Try The Dev-Only Example CLI

The repository dev environment installs a local `apprc` command from the
`examples/apprc_example_app` package. Use it to test setup, storage registries,
local dotenv overrides, JSON output, and the Textual editor before wiring
AppRC into another project. The published `apprc` wheel does not install this
command. `python -m apprc` is intentionally not a supported entrypoint.

After `uv sync --all-groups`, run:

```shell
export APPRC_EXAMPLE_APP_STORAGE="$PWD/.demo/storage"
.venv/bin/apprc config setup --yes --storage-root "$APPRC_EXAMPLE_APP_STORAGE"
.venv/bin/apprc config show --json
.venv/bin/apprc config set app.profile other-profile
.venv/bin/apprc config set retry_count 5
.venv/bin/apprc config set access_token secret-token
.venv/bin/apprc config edit
```

or use `uv run apprc ...` for the same commands.

The executable is `apprc`, but its disposable example files live under the
`apprc_example_app` namespace:

| Item | Default |
|---|---|
| Storage selector | `APPRC_EXAMPLE_APP_STORAGE` (required) |
| AppRC TOML selector | `APPRC_EXAMPLE_APP_APPRC_TOML` (optional multi-storage file) |
| Suggested active storage root | `~/.local/share/apprc_example_app/apprc_example_app_stor-1` |
| Local env | `~/.local/share/apprc_example_app/apprc_example_app_stor-1/.env.apprc_example_app` |

<br>

# Example

An application usually wires AppRC in three steps: declare fields, create the
kit, and mount the generated `config` CLI.

```python
from dataclasses import dataclass

import typer

from apprc import AppConfigKit, EnvConfig, env_field, env_owner

# 1) Declare the config fields your app owns.
@env_owner(
    key="app",
    title="App",
    env_prefix="MYAPP_",
    rc_path=("app",),
)
class AppEnv(EnvConfig):
    profile: str = env_field(
        "PROFILE",
        default="default",
        title="Profile",
        explanation_short="Named profile used by the application.",
    )

# 2) Create the reusable AppRC facade for your application.
MYAPP_CONFIG = AppConfigKit(
    app_name="myapp",
    display_name="MyApp",
    config_package="myapp.config",
    envs=(AppEnv,),
    storage_env_key="MYAPP_STORAGE",
    apprc_toml_filename="myapp.apprc.toml",
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

Runtime dataclasses inherit `EnvConfig` when you want typed objects populated from
the bootstrapped environment. `env_field(...)` carries env names, defaults,
docs labels, editor labels, choices, and redaction metadata. AppRC derives the
normalized owner inventory from that class for loading, validation, docs, CLI
commands, and the terminal editor.

### Config Package Convention

Put AppRC declarations in a real `<app>.config` package, for example
`myapp/config/owners.py`, and keep packaged shared defaults at
`myapp/config/.env.shared`. Set `AppConfigKit(config_package="myapp.config")`
so bootstrap can load those resources.

`config doctor` reports non-fatal convention warnings when
`config_package` does not end with `.config` or when an `EnvConfig` owner class
lives outside that package. JSON doctor payloads put these messages in
`warnings`, not `issues`, and they do not change the runtime readiness status.

Host applications should still mount the generated config CLI as a subcommand
of the application that depends on AppRC. Generated end-user prompts should
feel owned by that host application: a MyApp user should see MyApp setup text,
not AppRC implementation details. `app_name` drives paths and selectors,
`display_name` drives human-facing labels, and optional `command_name`
overrides the executable shown in generated next-step commands.

Users then get:

```shell
export MYAPP_STORAGE="/absolute/path/to/storage"
myapp config setup
myapp config setup --yes --storage-root "$MYAPP_STORAGE"
export MYAPP_APPRC_TOML="/absolute/path/to/config-dir/myapp.apprc.toml"
myapp config setup --yes --apprc-dir "/absolute/path/to/config-dir" --storage-root "$MYAPP_STORAGE" --multi-storage --name myapp_stor-1
myapp config init /absolute/path/to/storage --name myapp_stor-1
myapp config doctor
myapp config show --json
myapp config set app.profile other-profile
myapp config edit
```

Use `myapp config setup` for normal first-time installation. With no options it
opens a Textual wizard with path autocomplete, asks for an active storage root,
asks whether to enable multi-storage management, and shows next steps. For CI
or scripted single-storage bootstrap, pass `--yes --storage-root PATH`. Add
`--multi-storage --apprc-dir /absolute/path/to/config-dir --name NAME` when
setup should also create or reuse an AppRC TOML file and register the active
root. `config init`, `config list`, archive, restore, and register-active
workflows remain multi-storage features after `MYAPP_APPRC_TOML` is
exported.

### Bootstrap Recommendation

For AppRC-backed apps, keep the storage selector in startup:

- `export <APP>_STORAGE="/absolute/path/to/storage"`

`<APP>_STORAGE` is the active storage selector when the user exports it or one
or more explicit env files provide it. A packaged `.env.shared` may also provide
a lowest-precedence default selector for single-storage applications. The
selector is interpreted as a path when `<APP>_APPRC_TOML` is unset, including
bare relative values such as `alpha`. Set
`export <APP>_APPRC_TOML="/absolute/path/to/<app>.apprc.toml"` only when the app
should use multi-storage features. In multi-storage mode, exact
registered names resolve through the TOML, path-like values such as
`./project`, `/data/project`, `~/project`, and `C:/Projects/project` resolve as
paths, and bare unknown names fail with guidance.

Runtime behavior when keys are missing:

- `<APP>_APPRC_TOML` missing: single-storage mode is active. Runtime commands
  use `<APP>_STORAGE` as a path. Multi-storage commands such as `config list` and
  `config init` are unavailable until `<APP>_APPRC_TOML` is exported.
- `<APP>_STORAGE` missing everywhere: runtime bootstrap fails after checking
  `--storage`, already exported env values, explicit env files, and packaged
  `.env.shared` defaults. Setup and doctor commands can still run in partial
  setup states to help fix the missing selector.

<br>

# Explanations

### Config Model

`apprc` separates config into clear layers:

| Layer | Owner | Purpose |
|---|---|---|
| `env_field(...)` | application | One typed env-backed runtime attribute. |
| `@env_owner(...)` | application | A named section of related fields derived from an `EnvConfig` class. |
| `.env.shared` | application package | Packaged defaults shipped with code. |
| `<storage>/.env.local` | user/project | Per-storage local overrides. |
| Python args and assignments | application/library code | Highest-priority runtime values for one config object. |
| `os.environ` | current process | Env-backed values used when Python code does not override the field. |
| `<APP>_APPRC_TOML -> <app>.apprc.toml` | AppRC TOML | Optional named storage roots and archive restore metadata. |
| `<APP>_STORAGE` | Bootstrap selector | Active storage name or storage path for current shell context. |

Runtime dataclasses inherit `EnvConfig`. The dataclass owns Python attributes;
`env_field(...)` owns env names, defaults, docs labels, editor labels, choices,
and redaction metadata. AppRC derives `ConfigOwner` and `ConfigField` schema
objects from the class for internal tools.

### App / Env Mode

Applications use App / Env Mode when they want one effective runtime config
object built from declarations, Python constructor values, defaults, and the
current process environment.

```python
from apprc import EnvConfig, env_field, env_owner


@env_owner(
    key="app.runtime",
    title="App Runtime",
    env_prefix="MYAPP_",
    rc_path=("app",),
)
class AppEnv(EnvConfig):
    profile: str = env_field("PROFILE", default="default")
```

Constructing `AppEnv()` resolves the config object in this order:

1. Python constructor arguments, such as `AppEnv(profile="test")`
2. `EnvConfig` defaults declared by `env_field(...)`
3. current-process `os.environ` values for fields not already owned by Python
4. required-field, type, and choice validation

Call `AppConfigKit.bootstrap(...)` before constructing `EnvConfig` objects when
packaged, storage-local, or explicit dotenv layers should populate
`os.environ`.

### Library Mode

Library Mode is for reusable clients that accept an optional config object plus
simple convenience parameters. AppRC keeps the policy centralized on
`BaseConfig`:

```python
class LLMClient:
    def __init__(self, config: ClientConfig | None = None, model: str | None = None):
        self.config = ClientConfig.create_or_update(cfg=config, model=model)

    def prompt(self, text: str, model: str | None = None) -> str:
        cfg = self.config.scoped_from(locals())
        ...
```

Use `ConfigClass.create_or_update(cfg=cfg, field=value)` for persistent
per-instance values, for example constructor convenience arguments. Use
`cfg.scoped(field=value)` or `cfg.scoped_from(locals())` for per-call effective
config. Scoped configs are isolated clones: they validate like assignment,
record `python_scoped_override` provenance, and leave the original config
unchanged.

Inspect any effective value with `cfg.provenance_of("field_name")`, or inspect
the whole config object with `cfg.provenance()`.

### Runtime Provenance

`BaseConfig.provenance()` reports where each public config value came from.
Every `ConfigProvenance` record has a broad `source` and an exact `origin`:

| Boundary | Origins |
|---|---|
| `python` | `python_constructor_argument`, `python_runtime_assignment`, `python_scoped_override`, `python_baseconfig_default`, `python_envconfig_default`, `python_process_environment_mutation` |
| `shell` | `shell_export_variable`, `shell_dotenv_shared`, `shell_dotenv_local`, `shell_dotenv_explicit`, `shell_bootstrap_selector` |

`BaseConfig` records Python constructor arguments, dataclass defaults,
post-construction assignments, and isolated scoped override clones. `EnvConfig`
enriches env-backed fields with the env key and the winning shell-side origin
when AppRC bootstrap knows it. Dotenv-backed records include the source file
path. If a value AppRC recorded during bootstrap no longer matches the value
later read from `os.environ`, the origin is reported as
`python_process_environment_mutation`.

### Bootstrap Precedence

Applications call `AppConfigKit.bootstrap(...)` once at CLI startup. It merges:

1. packaged `.env.shared`
2. selected storage-local `.env.local`
3. explicit `--env-file` values, in command/API order
4. values already present in `os.environ`

Explicit env files are ordered; later files override earlier files. The merged
explicit values always override the packaged and storage-local dotenv layers. By
default, values already present in `os.environ` win over `--env-file`. Set
`env_file_overrides_os_environ=True` when explicit files should win inside the
current Python process. AppRC never mutates the parent shell. CLI applications
should expose repeatable `--env-file PATH` and
`--env-file-overrides-os-environ` with the `-o` shorthand.

Storage-root selection uses the same inputs before runtime config objects are
created: `--storage`, explicit env values or existing `os.environ` according to
`-o`, and then packaged `.env.shared` as the lowest-precedence fallback. That
lets an application ship a simple single-storage default while still allowing
users and deployment env files to override it.

AppRC intentionally mutates only the current Python process during bootstrap.
`typed-settings` and some runtime dependencies bind from `os.environ`, so the
bootstrap layer must populate that process before config dataclasses are
constructed. Normal runtime bootstrap never writes `.env.local`, never creates
storage roots, and never changes the parent shell; setup, register, editor, and
`config set` flows own those file writes.

Set `load_dotenv_layers=False` in Python, or expose a CLI flag such as
`--skip-dotenv-layers`, to skip merging packaged, storage-local, and explicit
dotenv values into the process. Registry and storage selection still run; the
explicit env files may still provide the AppRC TOML or storage selector used for
selection.

`Config modified: ...` warnings come from `BaseConfig.__setattr__` after a
runtime config object is constructed. They flag config-object reassignment, not
`os.environ` changes and not dotenv-file writes. Assigning an owner-backed field
also records a `python_runtime_assignment` origin that normal `reload()` calls
preserve; pass `reload(override_python_values=True)` only when env values should
replace Python-provided values. Scoped clones record `python_scoped_override`
instead and follow the same reload protection rules.

### Storage Registries

Globally installed commands need to find user data without hardcoding one path,
so AppRC uses one required rule: the app-specific `<APP>_STORAGE` environment
variable selects the active storage root. For an app named `myapp`, that
variable is `MYAPP_STORAGE`.

The app-specific `<APP>_APPRC_TOML` environment variable is optional. When it is
unset, AppRC runs in single-storage mode and treats every non-empty storage
selector as a path. When it is set, AppRC runs in multi-storage mode and uses
the TOML for named storage roots, archive metadata, and register-active
workflows.

Doctor status is explicit:

| State | Meaning |
|---|---|
| `env_not_set` | `<APP>_STORAGE` is missing. |
| `multi_storage_not_ready` | `<APP>_APPRC_TOML` is set for multi-storage mode but points to a missing or invalid file. |
| `storage_not_ready` | The selected storage root or local env file is missing, or a multi-storage selector cannot be resolved. |
| `runnable` | `<APP>_STORAGE` resolves to an existing storage root with a local env file; the optional AppRC TOML is either unset or valid. |

In `config doctor --json`, use `status == "runnable"` as the readiness check.

For example:

```toml
[storages.myapp_stor-1]
root = "/absolute/path/to/storage"

[archived_storages.old-default]
archive = "/absolute/path/to/old-default.apprc.tar.xz"
source_root = "/absolute/path/to/old-default"
```

Each storage root owns its own local override file, such as `.env.local`.
Archived storage records are only last-known restore shortcuts for the
terminal editor; runtime bootstrap still selects live directory entries from
`[storages]`.

On POSIX/WSL hosts, Windows drive paths such as `D:\Training\demo-project` are
normalized to usable local paths before AppRC writes the AppRC TOML or reads a
storage-root environment value.

**Important**

POSIX shells consume unquoted backslashes before Python sees the argument.
If you type `C:\Projects\demo-storage` without quotes, AppRC may receive
`C:Projectsdemo-storage`, which is not recoverable as a real Windows path.
Use one of these forms instead:

```shell
myapp config init 'C:\Projects\demo-storage' --name myapp_stor-1
myapp config init C:/Projects/demo-storage --name myapp_stor-1
myapp config init /mnt/c/Projects/demo-storage --name myapp_stor-1
```

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

from apprc import EnvConfig, env_field, env_owner

@env_owner(
    key="storage",
    title="Storage",
    env_prefix="MYAPP_",
    rc_path=("storage",),
)
class StorageEnv(EnvConfig):
    root: Path = env_field(
        "STORAGE",
        editable=False,
        required=True,
        explanation_short="Active storage root.",
        explanation_long="Selected by the <APP>_STORAGE bootstrap value.",
    )
```

Use `editable=False` for values owned by the AppRC TOML instead of `.env.local`.

### Bootstrap a CLI

Call bootstrap before creating runtime config objects.

```python
from apprc.cli import bootstrap_cli_env
from apprc.logging import setup_logging

state.env_bootstrap = bootstrap_cli_env(
    MYAPP_CONFIG,
    env_files=env_files,
    env_file_overrides_os_environ=env_file_overrides_os_environ,
    load_dotenv_layers=not skip_dotenv_layers,
    storage=storage,
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

`config setup` opens a Textual wizard for first-time setup unless `--yes` is
passed for non-interactive use. The wizard handles active storage root
creation, optional multi-storage registration, existing registries, custom app
directories (AppRC), and final diagnostics.

`config edit` opens a Textual editor. The editor shows:

- key number
- section
- env key
- shell status
- local value
- default value
- short explanation

Selecting a row opens a modal with type information, possible values, the long
explanation, and copy buttons for the effective, shell, local, and shared
default values that are currently available. Secret values are redacted on
screen, but an explicit copy action copies the raw value. Required missing
values show `<required>`.

When `<APP>_APPRC_TOML` is set, the editor also manages multi-storage
storage lifecycle:

- `New storage` registers a directory or restores a `*.apprc.tar.xz` archive.
- `Register active storage` registers an unregistered `<APP>_STORAGE` path.
- `Delete storage` can unregister only or delete the directory too.
- `Archive storage` writes `*.apprc.tar.xz` and can optionally remove the
  source directory after compression.
- Missing registered roots stay visible and can be unregistered without
  recreating their directories.

### Use Logging

```python
from apprc.logging import get_logger, setup_logging

setup_logging(level="INFO", renderer="cli")
log = get_logger(__name__)

log.action_begin("Loading workspace")
log.success("Workspace ready", storage="myapp_stor-1")
```

<br>

# References

### Important Modules

| Module | Look Here For |
|---|---|
| `apprc` | Preferred app-facing facade for runtime config, schema, storage, local-env, and logging interfaces. |
| `apprc.runtime_config` | Narrow advanced runtime-config facade for lower-level integration work. |
| `apprc.runtime_config.app_spec` | `AppConfigSpec`, the application integration declaration behind the kit. |
| `apprc.runtime_config.kit` | `AppConfigKit`, the high-level app integration facade. |
| `apprc.runtime_config.contract` | Schema records, lookup, validation, and AppRC TOML contract helpers. |
| `apprc.runtime_config.config_objects` | Config object classes and declaration helpers: `BaseConfig`, `EnvConfig`, `env_field`, and `env_owner`. |
| `apprc.runtime_config.provenance` | `ConfigProvenance`, source/origin literals, and bootstrap env-origin registry. |
| `apprc.runtime_config.bootstrap` | CLI startup dotenv precedence and process-env mutation boundary. |
| `apprc.runtime_config.storage` | Storage roots, local dotenv files, registries, paths, selectors, and archives. |
| `apprc.runtime_config.storage.loading` | Storage table loading paths by setup, runtime, and diagnostic intent. |
| `apprc.runtime_config.storage.selector` | `<APP>_STORAGE` registered-name and explicit-path resolution. |
| `apprc.runtime_config.doctor` | `config doctor` payloads, statuses, and setup guidance. |
| `apprc.runtime_config.setup` | Shared setup workflow rules and user-facing setup copy. |
| `apprc.runtime_config.terminal_styles` | Shared Rich text helpers for CLI and TUI output. |
| `apprc.runtime_config.tui` | Textual config editor and setup wizard package. |
| `apprc.runtime_config.tui.editor` | Textual config editor app and storage workflows. |
| `apprc.runtime_config.tui.setup` | Textual setup wizard app. |
| `apprc.runtime_config.tui.modals` | Textual modal screens for value and storage operations. |
| `apprc.runtime_config.tui.primitives` | Shared Textual path, name, and confirmation modals. |
| `apprc.cli.config` | Generated `config` Typer command package. |
| `apprc.cli.config.app` | Typer command factory for generated config CLIs. |
| `apprc.cli.config.handlers` | Behavior behind generated config commands. |
| `apprc.cli.bootstrap` | Common root CLI bootstrap options. |
| `apprc.logging` | Logging facade: `setup_logging`, `get_logger`, `AppLogger`. |

### Important Config Types

| Type | Meaning |
|---|---|
| `AppConfigKit` | Convenient object applications keep around. |
| `AppConfigSpec` | Frozen declaration behind the kit. |
| `env_owner(...)` | Decorator that turns an `EnvConfig` class into one config section. |
| `env_field(...)` | Dataclass field helper for one env-backed runtime attribute. |
| `ConfigOwner` | Derived schema for one config section, env prefix, runtime path, and fields. |
| `ConfigField` | Derived schema for one editable or read-only env-backed setting. |
| `ConfigDoctorStatus` | `env_not_set`, `multi_storage_not_ready`, `storage_not_ready`, or `runnable`. |
| `EnvConfig` | Runtime dataclass base that resolves Python, env, and EnvConfig-default values. |
| `ConfigProvenance` | Provenance record returned by `BaseConfig.provenance_of()` and `BaseConfig.provenance()`. |
| `EnvBootstrapResult` | Files and storage selected during CLI startup. |
| `StorageRegistry` | Parsed AppRC TOML storage table. |
| `ArchivedStorageRecord` | Last-known archive path for editor restore shortcuts. |
| `LocalEnvUpdate` | Result of writing one local dotenv override. |

### Config CLI Commands

| Command | Purpose |
|---|---|
| `config setup` | Open the setup wizard, or run non-interactively with `--yes`. |
| `config init STORAGE_ROOT --name NAME` | Register a storage root in multi-storage mode. |
| `config doctor` | Diagnose the selected storage and optional AppRC TOML state. |
| `config show --json` | Print resolved runtime config payload. |
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

### Test Against A Downstream App

If you maintain a host application that depends on AppRC, install the local
checkout there and run that application's tests:

```shell
cd /path/to/host-app
.venv/bin/python -m pip install --no-deps --no-build-isolation -e ../apprc
.venv/bin/pytest
```

Keep refactors behavior-preserving. If a cleanup would remove a public module,
change import-time side effects, or alter CLI output, treat that as a feature
change and ask first.
