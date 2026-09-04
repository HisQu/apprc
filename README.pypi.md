# `apprc`: Application Runtime Config

<p align="center">
  <a href="https://github.com/HisQu/apprc/actions/workflows/ci.yml"><img src="https://github.com/HisQu/apprc/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="https://pypi.org/project/apprc/"><img src="https://img.shields.io/pypi/v/apprc" alt="PyPI version"></a>
  <a href="https://pypi.org/project/apprc/"><img src="https://img.shields.io/pypi/pyversions/apprc" alt="Supported Python versions"></a>
  <a href="https://github.com/HisQu/apprc/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/apprc" alt="MIT license"></a>
</p>

AppRC is for Python applications that need configuration to be explicit,
inspectable, and pleasant to operate. Instead of spreading environment
variables, dotenv files, setup commands, and diagnostics across unrelated code,
you declare the runtime contract once and let AppRC build the surrounding
workflows from that metadata.

The three strongest parts:

- **Typed config contracts:** declare application settings once with
  `rc.Config`, `rc.ConfigBase`, `rc.field(...)`, and `@MyRC.config(...)`.
- **Deterministic runtime config:** load layered dotenv files predictably while
  keeping normal runtime reads and diagnostics zero-write.
- **Generated operator UX:** mount ready-made Typer `config` commands and open
  the same contract in the Textual editor.

Advanced integrations can inspect the same declared contract through
intentional namespaces such as `rc.cli`, `rc.files`, `rc.storage`,
`rc.provenance`, and `rc.schema`; normal app code should still start with
`import apprc as rc`.

<p align="center">
  <img src="https://raw.githubusercontent.com/HisQu/apprc/main/docs/assets/apprc-abstract-user-journey.svg" alt="AppRC graphical abstract" width="100%">
</p>

<p align="center">
  <strong>Fig. 1 - AppRC Graphical Abstract:</strong>
  AppRC lets developers ship one typed config contract with generated setup,
  diagnostics, editing, and runtime config workflows.
</p>

**Note**

For the full system model, see
[docs/Explanations.md](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md). For exact public names and
command references, see [docs/References.md](https://github.com/HisQu/apprc/blob/main/docs/References.md).

<br>

## Table Of Contents

1. [`apprc`: Application Runtime Config](#apprc-application-runtime-config)
   1. [Table Of Contents](#table-of-contents)
2. [Installation](#installation)
3. [Quickstart](#quickstart)
4. [Runnable Examples](#runnable-examples)
5. [How AppRC Works](#how-apprc-works)
   1. [Mental Model](#mental-model)
   2. [Config And Storage](#config-and-storage)
   3. [Runtime Precedence](#runtime-precedence)
6. [Generated Workflows](#generated-workflows)
   1. [Config CLI](#config-cli)
   2. [Setup And Diagnostics](#setup-and-diagnostics)
7. [More Documentation](#more-documentation)
   1. [Detailed Manual](#detailed-manual)
   2. [Development](#development)

<br>

<br>



Install AppRC, declare the runtime contract, and mount the generated `config`
commands in your Typer application.

<br>

# Installation

```shell
python -m pip install apprc
```

Install the optional Textual editor when you want `config edit`:

```shell
python -m pip install "apprc[tui]"
```

AppRC supports Python 3.12 and newer.

**Note**

For installation and first-setup recipes, see
[docs/How-To-User-Guides.md](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md).

<br>

# Quickstart

Use one root import and declare the app contract from that handle:

Create this standard package layout by hand, or generate a starter with
`apprc scaffold config`:

```text
myapp/config/
  __init__.py
  __init__.pyi
  _facade.py
  app.py
  sections/
    __init__.py
    __init__.pyi
    _facade.py
    app.py
  bundle.py
  catalog.py
```

```bash
apprc scaffold config \
  --package myapp \
  --storage \
  --app-id myapp \
  --display-name "My App" \
  --storage-selector-env-key MYAPP_STORAGE \
  --target src
```

The full declaration can live in one file while learning, but the package
layout above is the recommended project structure.

Keep every app-declared config area under `config/sections/`. Small areas can
be one module, for example `sections/client.py`. When an area grows, turn it
into a package such as `sections/rag/` and keep its local bundle/resources next
to its leaf settings there. Leave `config/bundle.py` for the top-level app
bundle and `config/catalog.py` for metadata. Keep package `__init__.py` files
lightweight; import section classes in `bundle.py` from leaf modules such as
`config.sections.client`, not from the `config.sections` package facade.

```python
from dataclasses import dataclass, field
from pathlib import Path

import typer
import apprc as rc


MyRC = rc.AppRC(
    app_id="myapp",
    display_name="My App",
    config_package="myapp.config",
    storage=rc.Storage(selector_env_key="MYAPP_STORAGE"),
)


@MyRC.config("app", prefix="MYAPP_", title="App")
class AppSettings(rc.Config):
    storage_root: Path = rc.field(
        "MYAPP_STORAGE",
        editable=False,
        required=True,
        title="Storage root",
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
    )


@MyRC.config("resources", title="Resources")
class PackageResources(rc.ConfigBase):
    package: str = "myapp.resources"


@MyRC.bundle
@dataclass(kw_only=True)
class MyAppConfig:
    app: AppSettings = field(default_factory=AppSettings)
    resources: PackageResources = field(default_factory=PackageResources)
```

Add packaged defaults in `myapp/config/apprc.defaults.env`:

```dotenv
MYAPP_PROFILE="default"
```

Mount AppRC on your Typer application before commands construct runtime config
objects:

```python
from myapp.config import MyAppConfig, MyRC

app = typer.Typer()
MyRC.mount_cli(app)


@app.command()
def run() -> None:
    cfg = MyAppConfig()
    typer.echo(f"profile={cfg.app.profile}")
```

`MyRC.mount_cli(...)` adds the standard AppRC CLI runtime options, performs
runtime setup for commands that need resolved config, and mounts the generated
`config` command group. Apps with custom runtime state can pass
advanced options through `rc.cli.mount_config_cli(...)` or `rc.cli.CliRuntime`.
Apps that own their Typer callback and extra options can use
`rc.cli.CliRuntime` as the composable middle layer: the app builds its runtime
state, while AppRC
owns config command mounting, skip policy, context storage, and state
validation. When `runtime.prepare(...)` skips runtime setup,
`session.runtime_setup_skipped` is true and `session.state` is `None`.
Runtimeful generated config commands require the app callback to leave the
declared `state_type` on `ctx.obj`; runtime-independent config commands use
AppRC's stored context instead.

For non-Typer usage, call bootstrap explicitly and then construct config:

```python
MyRC.bootstrap()
cfg = MyAppConfig()
```

`Config()` reads the current process environment at construction time.
Bootstrap is needed when AppRC should first merge its managed dotenv files;
it is not a requirement for tests or callers that deliberately use only
constructor values, Python defaults, and the current `os.environ`.

High-level convenience boundaries that want AppRC defaults without taking
bootstrap options can call `MyRC.ensure_bootstrapped()`. It performs the
default bootstrap once per `AppRC` declaration and reuses the successful
result. Keep explicit policy at the application entrypoint: call
`MyRC.bootstrap(...)` there when storage selection, env files, or precedence
options vary. Libraries should normally accept a constructed config object
from their caller.

`rc.field("ENV_KEY")` is required when no default is provided.
`rc.field("ENV_KEY", default="x")` and `default_factory=...` are optional.
An explicit `required=True` cannot be combined with either Python fallback;
put the value in `apprc.defaults.env` and describe it with
`packaged_default=...`, or pass the value to the config constructor.
`secret=True` redacts display output; it does not encrypt values, store them
elsewhere, or imply that the field is required.

Install the local library plus its runnable examples from a checkout with:

```bash
python -m pip install -e ".[tui]" -e examples/example_apps --no-build-isolation
```

Start with `apprc-examples-lab config-with-storage`. It opens a disposable
shell with no AppRC files and prints commands for the selected scenario. See
[Runnable Examples](#runnable-examples) for the complete inventory.

**Note**

For the step-by-step integration guide, see
[docs/How-To-User-Guides.md#integrate-apprc](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#integrate-apprc).
For the exact import surface, see
[docs/References.md#public-interfaces](https://github.com/HisQu/apprc/blob/main/docs/References.md#public-interfaces).

<br>

<br>

# Runnable Examples

The checkout contains four application CLIs and two test utilities:

| Command | Storage | What it demonstrates |
|---|---:|---|
| `apprc-config-only` | No | The smallest `AppRC` integration with packaged, user, explicit-file, and process-environment values. |
| `apprc-config-with-storage` | Yes | Named storage, direct path selection, storage-local dotenv values, and the generated storage lifecycle. |
| `apprc-explicit-env-precedence` | Yes | The difference between normal process-environment precedence and `--env-file-overrides-os-environ`. |
| `apprc-cli-runtime` | Yes | An app-owned Typer callback, custom runtime state, and runtime-independent commands through `CliRuntime`. |
| `apprc-examples-lab EXAMPLE` | Depends | Opens one clean temporary shell, prints a walkthrough, and deletes its temporary state when the shell exits. |
| `apprc-examples-run-all` | Both | Runs setup, doctor, application runtime, and purge through the installed CLIs, then prints a JSON summary. |

Use the lab for manual testing:

```bash
apprc-examples-lab config-only
apprc-examples-lab config-with-storage
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
```

The lab removes inherited `APPRC_EXAMPLE_*` values and points the selected
application's `<APP>_APPRC_DIR` at its temporary root. It does not create
AppRC files before the shell opens. The root is removed on exit. A storage
path that you explicitly choose outside the printed temporary root remains
untouched.

The four application commands are normal applications: if you invoke them
outside the lab, they use their configured or default AppRC paths and can
leave persistent files. Run `config paths` before setup and `config purge
--dry-run` before removal.

All four examples expose `config paths`, `setup`, `doctor`, `show`, `set`,
`edit`, `migrate`, and `purge`. The three storage-capable examples also expose
`config storage add`, `list`, `select`, `rename`, `repoint`, `move`, and
`remove`, plus the root `--storage NAME_OR_PATH` option. Their package source
is intentionally self-contained so each example can be copied without the
lab or smoke-runner package.

The automated example suite checks the common command surface on every app,
the complete storage lifecycle on `apprc-config-with-storage`, name and path
selection, both precedence outcomes, `CliRuntime` skip/runtime behavior, and
temporary-lab cleanup. It does not claim that every generated command is run
against every example.

See [examples/example_apps/README.md](https://github.com/HisQu/apprc/blob/main/examples/example_apps/README.md) for
copyable walkthroughs and source links.

<br>

# How AppRC Works

AppRC starts from one declared contract, then uses that contract to load
runtime values, inspect configuration health, write explicit setup files, and
generate user-facing configuration tools.

| ![One AppRC contract feeding many workflows](https://raw.githubusercontent.com/HisQu/apprc/main/docs/assets/apprc-abstract-contract-workflows.svg) |
|:--:|
| **Fig. 2 - One Contract, Many Workflows:** AppRC reuses the same contract metadata for runtime loading, provenance, diagnostics, generated CLI commands, and the editor. |

<br>

## Mental Model

AppRC has one contract and several workflows built from it.

| Concept | Meaning |
| --- | --- |
| Config field | One typed setting declared with `rc.field("FULL_ENV_KEY", ...)`. |
| Registered config | A related group of fields declared by `@MyRC.config(...)`. |
| AppRC facade | The app-level contract that selects supported persistence layers. |
| Bootstrap | An optional startup step that merges managed dotenv layers into this Python process. |
| Config construction | A read of Python values and the current `os.environ` into a mutable config object. |
| Generated CLI | A reusable Typer `config` command group for inspection and edits. |
| Editor | A Textual view over the same sections, fields, and dotenv layers. |

**Note**

For the deeper architecture behind registered sections, fields, config layers,
provenance, and the zero-write policy, see
[docs/Explanations.md#runtime-config-model](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#runtime-config-model).

<br>

## Config And Storage

There are two declarations, not four capability levels:

```python
# Config only. No storage controls are generated.
MyRC = rc.AppRC(
    app_id="myapp",
    config_package="myapp.config",
)

# The same config model plus storage.
MyRC = rc.AppRC(
    app_id="myapp",
    config_package="myapp.config",
    storage=rc.Storage(selector_env_key="MYAPP_STORAGE"),
)
```

`rc.Storage()` derives `MYAPP_STORAGE` when `selector_env_key` is omitted. The
first setup suggests `~/.local/share/myapp/storage/` on every operating system.
The user sees that path before AppRC creates it and can pass another path with
`config setup --storage-root PATH`. Interactive setup offers the default path,
a custom path with directory completion, or cancellation.

AppRC-managed persistence files are explicit:

| Layer | Default location | Created by |
| --- | --- | --- |
| Packaged defaults | package `apprc.defaults.env` | shipped with package |
| User dotenv | `~/.local/share/myapp/apprc.user.env` | `config setup` or first user-scope save |
| Storage registry | `~/.local/share/myapp/apprc.toml` | storage setup or a storage registry command |
| Storage dotenv | `<storage-root>/apprc.storage.env` | storage setup, `storage add`, or first storage-scope save |

The directory containing `apprc.user.env` and `apprc.toml` is the **AppRC
directory**. Set `MYAPP_APPRC_DIR` to relocate the complete directory. AppRC
does not split default files between `.config`, `.local`, `%APPDATA%`, and
`~/Library/Application Support`.

The complete default layouts are:

```text
# rc.AppRC(...) — no storage
~/.local/share/myapp/
└── apprc.user.env

# rc.AppRC(..., storage=rc.Storage()) — one default storage
~/.local/share/myapp/
├── apprc.user.env
├── apprc.toml
└── storage/
    └── apprc.storage.env
```

Additional storage names are user-owned registry entries. Their roots may be
anywhere; they do not gain another `storage/<name>/` directory automatically.

**Important**

Files on disk never enable application capabilities. Only
`storage=rc.Storage()` enables storage support. Without it, AppRC hides
`--storage`, `config storage ...`, the storage editor section, and
`--scope storage`; a stale `apprc.toml` produces only a doctor warning.

**Note**

For declaration arguments, see
[docs/References.md#application-declaration](https://github.com/HisQu/apprc/blob/main/docs/References.md#application-declaration).

<br>

## Runtime Precedence

When dotenv layers are loaded, AppRC merges values in this order:

1. packaged `apprc.defaults.env`
2. user `apprc.user.env`
3. selected storage `apprc.storage.env`, when storage is selected and present
4. explicit `--env-file` values
5. existing `os.environ`

With `--env-file-overrides-os-environ`, explicit env files move after
`os.environ` and win over shell exports.

Storage selector resolution accepts registered names and filesystem paths:

1. CLI `--storage`
2. process environment or explicit env files, in the order selected by
   `--env-file-overrides-os-environ`
3. `selected_storage` in `apprc.toml`

`apprc.user.env`, `apprc.storage.env`, and packaged defaults never select a
storage. A direct path must be an existing directory with a readable
`apprc.storage.env`. Relative selectors such as `./data` resolve from the
directory containing `apprc.toml`, never from the current working directory.
When a path matches one registered root, AppRC reports its name. An initialized
unregistered path is usable for one run; an interactive CLI offers to register
it, while a non-interactive caller performs no registry writes.

**Note**

For the rationale behind layer order and storage selector resolution, see
[docs/Explanations.md#runtime-bootstrap](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#runtime-bootstrap)
and [docs/Explanations.md#storage-selection](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#storage-selection).
For exact precedence tables, see
[docs/References.md#runtime-precedence](https://github.com/HisQu/apprc/blob/main/docs/References.md#runtime-precedence).

<br>

<br>

# Generated Workflows

Mount the generated workflows when you want your application to expose the same
contract to users, setup commands, diagnostics, and the Textual editor.

<br>

## Config CLI

Mounting `APP_CONFIG.typer_app(...)` gives your app these commands:

```shell
myapp config paths
myapp config doctor
myapp config show
myapp config setup
myapp config migrate --dry-run
myapp config purge --dry-run
myapp config set KEY VALUE --scope user
myapp config set KEY VALUE --scope storage
myapp config edit
myapp config storage add NAME PATH
myapp config storage list
myapp config storage select NAME
myapp config storage rename NAME NEW_NAME
myapp config storage repoint NAME PATH
myapp config storage move NAME PATH
myapp config storage remove NAME
```

Storage commands appear when the declaration includes `rc.Storage()`. The app
config commands are always available.

`config edit` requires the optional TUI extra:
`python -m pip install "apprc[tui]"`.

The editor always shows `Setup`. It runs the same declaration-aware setup as
`config setup`. Storage apps also show `New`, `Register`,
`Rename`, `Location`, `Move`, `Archive`, and `Delete`. `New` and `Register`
can create the first AppRC TOML registry; opening the editor itself still
writes nothing.

**Note**

For the generated command table, see
[docs/References.md#generated-cli-commands](https://github.com/HisQu/apprc/blob/main/docs/References.md#generated-cli-commands).

<br>

## Setup And Diagnostics

Use `config paths` before setup to see candidate paths and the declaration
without writing anything. Use `config setup` or the editor's
`Setup` action for explicit first storage setup, then use `config doctor` when
a machine is not runnable.

```shell
myapp config paths
myapp config setup --yes --storage-root /absolute/path/to/storage
myapp config doctor
myapp config set access_token secret-value --scope storage
myapp run
```

Setup creates the empty `apprc.user.env`, registers the initial storage as
`default`, records it as `selected_storage`, and creates
`apprc.storage.env`. No selector is written to a dotenv file and no shell
export is required. On an interactive terminal, the first storage-dependent
runtime command can offer the same setup. Use `--storage-root PATH` for a
custom path so the shell can complete it.

`config doctor` reports a status such as `storage_not_selected`,
`storage_not_ready`, `user_dotenv_not_ready`,
`storage_registry_not_ready`, or `runnable`.

`config set` changes only the requested dotenv assignment. It preserves
unrelated comments, blank lines, quoting, `export` prefixes, and ordering. If
the key has multiple active assignments, AppRC updates the first and comments
out the later assignments. The interactive CLI and editor require confirmation
before that cleanup. Non-interactive commands write the change and print a
warning afterward.

AppRC migrates the released 0.19 layout only. Inspect and apply it explicitly:

```shell
myapp config migrate --dry-run
myapp config migrate --yes
```

Migration finds platform-specific 0.19 directories, custom
`MYAPP_APPRC_TOML` locations, `.env.apprc-app`, `.env.apprc-storage`, and
path-valued `MYAPP_STORAGE`. It converts a path selector into the named
`default` storage and removes structural selector keys from the migrated user
dotenv. The unreleased `apprc.app.env` name is intentionally ignored.

Package uninstallers do not remove these user-owned files. Before uninstalling
an AppRC application, run `config purge --dry-run`, review the exact targets,
then run `config purge --yes` if desired. Purge deletes fixed AppRC files and
registered storage roots strictly inside the AppRC directory. For external
storage roots it deletes only `apprc.storage.env` and keeps all other data.
It never follows symlinks and removes the AppRC directory only when empty.

**Caution**

A registered internal storage root is application-owned. `config purge`
recursively deletes that root, including files AppRC did not create. Always
inspect the dry run first.

**Important**

Runtime reads and diagnostics do not create files. `bootstrap`, `config
paths`, `config doctor`, and opening `config edit` are zero-write. Editor
actions such as `Setup`, `New`, and `Register` write only after confirmation. For
storage-backed applications, bootstrap requires the selected root to exist
and be a directory. Run `config setup` before runtime startup.

**Note**

For doctor troubleshooting, see
[docs/How-To-User-Guides.md#troubleshoot-config-doctor](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#troubleshoot-config-doctor).
For exact status names, see
[docs/References.md#doctor-statuses](https://github.com/HisQu/apprc/blob/main/docs/References.md#doctor-statuses).

<br>

# More Documentation

The README stays short. The detailed manual and maintainer workflow live in
the documentation directory.

<br>

## Detailed Manual

The detailed manual starts at [docs/README.md](https://github.com/HisQu/apprc/blob/main/docs/README.md).

**Note**

Use [docs/How-To-User-Guides.md](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md) for integration
recipes, [docs/Explanations.md](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md) for the AppRC system
model, [docs/References.md](https://github.com/HisQu/apprc/blob/main/docs/References.md) for exact commands, files,
and APIs, and [docs/Development.md](https://github.com/HisQu/apprc/blob/main/docs/Development.md) for maintainer
workflow and docs rules.

The repository also ships runnable example CLIs in
[examples/example_apps](https://github.com/HisQu/apprc/blob/main/examples/example_apps). Each example is its own
package, with a `config/` package,
`cli.py`, and packaged `config/apprc.defaults.env` defaults so the source tree mirrors
a real app integration. Use `apprc-examples-lab` to keep manual test state
temporary.

<br>

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

**Note**

For maintainer workflow, documentation rules, and verification commands, see
[docs/Development.md](https://github.com/HisQu/apprc/blob/main/docs/Development.md).
