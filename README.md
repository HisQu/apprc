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
  <img src="docs/assets/apprc-abstract-user-journey.svg" alt="AppRC graphical abstract" width="100%">
</p>

<p align="center">
  <strong>Fig. 1 - AppRC Graphical Abstract:</strong>
  AppRC lets developers ship one typed config contract with generated setup,
  diagnostics, editing, and runtime config workflows.
</p>

> [!NOTE]
> For the full system model, see
> [docs/Explanations.md](docs/Explanations.md). For exact public names and
> command references, see [docs/References.md](docs/References.md).

<br>

## Table Of Contents

1. [`apprc`: Application Runtime Config](#apprc-application-runtime-config)
   1. [Table Of Contents](#table-of-contents)
2. [Installation](#installation)
3. [Quickstart](#quickstart)
4. [Runnable Examples](#runnable-examples)
5. [How AppRC Works](#how-apprc-works)
   1. [Mental Model](#mental-model)
   2. [Managed File Capabilities](#managed-file-capabilities)
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

> [!NOTE]
> For installation and first-setup recipes, see
> [docs/How-To-User-Guides.md](docs/How-To-User-Guides.md).

<br>

# Quickstart

Use one root import and declare the app contract from that handle:

`rc.AppRC`, `rc.Config` or `rc.ConfigBase`, and `rc.field(...)` are the complete
declaration API. `rc.schema` only inspects the normalized result.

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
  --user-dotenv \
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
    user_dotenv=rc.UserDotenv(),
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

Optionally add packaged defaults in `myapp/config/apprc.defaults.env`:

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

Start with `apprc-examples-lab user-dotenv-with-storage`. It opens a disposable
shell with no AppRC files and prints commands for the selected scenario. See
[Runnable Examples](#runnable-examples) for the complete inventory.

> [!NOTE]
> For the step-by-step integration guide, see
> [docs/How-To-User-Guides.md#integrate-apprc](docs/How-To-User-Guides.md#integrate-apprc).
> For the exact import surface, see
> [docs/References.md#public-interfaces](docs/References.md#public-interfaces).

<br>

<br>

# Runnable Examples

The checkout contains four capability examples, two advanced examples, and two
test utilities:

| Command | User dotenv | Storage | What it demonstrates |
|---|---:|---:|---|
| `apprc-process-env` | No | No | Process environment and Python defaults without managed user files. |
| `apprc-user-dotenv` | Yes | No | One managed user dotenv and the user write scope. |
| `apprc-storage` | No | Yes | Named storage and storage-local values without a user dotenv. |
| `apprc-user-dotenv-with-storage` | Yes | Yes | Both persistent capabilities and both write scopes. |
| `apprc-explicit-env-precedence` | Yes | Yes | Normal process precedence versus `--env-file-overrides-os-environ`. |
| `apprc-cli-runtime` | Yes | Yes | App-owned Typer state and runtime-independent commands through `CliRuntime`. |
| `apprc-examples-lab EXAMPLE` | Depends | Depends | One clean temporary shell with a scenario walkthrough. |
| `apprc-examples-run-all` | All | All | Automated setup, diagnostics, runtime, and cleanup through installed CLIs. |

Use the lab for manual testing:

```bash
apprc-examples-lab process-env
apprc-examples-lab user-dotenv
apprc-examples-lab storage
apprc-examples-lab user-dotenv-with-storage
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
```

The lab removes inherited `APPRC_EXAMPLE_*` values. For examples with managed
files, it points `<APP>_APPRC_DIR` at its temporary root. It does not create
AppRC files before the shell opens. The root is removed on exit. A storage path
that you explicitly choose outside the printed temporary root remains
untouched.

The commands are normal applications. Managed-capability examples use their
configured or default AppRC paths outside the lab and can leave persistent
files. Run `config paths` before setup and `config purge --dry-run` before
removal.

Every example exposes `config paths`, `show`, `doctor`, and cleanup-only
`purge`. `setup`, `set`, `edit`, and `migrate` appear only when the declaration
contains `rc.UserDotenv()` or `rc.Storage()`. Storage declarations also expose
the root `--storage NAME_OR_PATH` option and `config storage ...` commands.

The automated example suite checks the common command surface on every app,
the complete storage lifecycle on `apprc-storage`, name and path
selection, both precedence outcomes, `CliRuntime` skip/runtime behavior, and
temporary-lab cleanup. It does not claim that every generated command is run
against every example.

See [examples/example_apps/README.md](examples/example_apps/README.md) for
copyable walkthroughs and source links.

<br>

# How AppRC Works

AppRC starts from one declared contract, then uses that contract to load
runtime values, inspect configuration health, write explicit setup files, and
generate user-facing configuration tools.

| ![One AppRC contract feeding many workflows](docs/assets/apprc-abstract-contract-workflows.svg) |
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

> [!NOTE]
> For the deeper architecture behind registered sections, fields, config layers,
> provenance, and the zero-write policy, see
> [docs/Explanations.md#runtime-config-model](docs/Explanations.md#runtime-config-model).

<br>

## Managed File Capabilities

User-wide dotenv overrides and named storage are independent features:

```python
common = {"app_id": "myapp", "config_package": "myapp.config"}

process_only = rc.AppRC(**common)
user_only = rc.AppRC(**common, user_dotenv=rc.UserDotenv())
storage_only = rc.AppRC(**common, storage=rc.Storage())
both = rc.AppRC(
    **common,
    user_dotenv=rc.UserDotenv(),
    storage=rc.Storage(),
)
```

Capabilities are required by default, which preserves the setup behavior of
earlier releases. Use `required=False` when an application should expose the
managed layer without making it a prerequisite for every command:

```python
optional_persistence = rc.AppRC(
    **common,
    user_dotenv=rc.UserDotenv(required=False),
    storage=rc.Storage(required=False),
)
```

An optional declaration still exposes setup, editing, and storage management.
Bootstrap loads it when it exists. With no selected storage, runtime continues
using packaged defaults, explicit dotenv files, and the process environment.
Generated `config show` also continues when the application's runtime payload
supports a storage-free view.
Invalid selectors and broken selected roots remain errors. A malformed
registry remains an error unless an explicit initialized path uses AppRC's
existing one-run fallback.

A command that needs storage can enforce that requirement at its runtime
boundary:

```python
storage_runtime = rc.cli.CliRuntime(
    optional_persistence.kit,
    storage_required=True,
)
```

This does not change the application declaration. Other runtimes using the
same `AppRC` can keep storage optional.

`rc.Storage()` derives `MYAPP_STORAGE` when `selector_env_key` is omitted. The
first setup suggests `~/.local/share/myapp/storage/` on every operating system.
Interactive setup first lets the user accept or replace the AppRC directory,
then does the same for the storage root. Both path prompts provide filesystem
completion. Scripts can pass `--apprc-dir PATH` and `--storage-root PATH`.

AppRC-managed persistence files are explicit:

| Layer | Default location | Availability and creation |
| --- | --- | --- |
| Packaged defaults | package `apprc.defaults.env` | Optional application resource; never created for the user. |
| User dotenv | `~/.local/share/myapp/apprc.user.env` | Only with `rc.UserDotenv()`; created by setup. |
| Storage registry | `~/.local/share/myapp/apprc.toml` | Only with `rc.Storage()`; created by storage setup or registry commands. |
| Storage dotenv | `<storage-root>/apprc.storage.env` | Only with `rc.Storage()`; created by setup or `storage add`. |

The directory containing the declared central files is the **AppRC directory**.
Set `MYAPP_APPRC_DIR` to relocate it. AppRC does not split default files between
`.config`, `.local`, `%APPDATA%`, and `~/Library/Application Support`.

The complete default layouts are:

```text
# rc.AppRC(...) — process environment only
# No AppRC directory or managed user files.

# rc.AppRC(..., user_dotenv=rc.UserDotenv())
~/.local/share/myapp/
└── apprc.user.env

# rc.AppRC(..., storage=rc.Storage())
~/.local/share/myapp/
├── apprc.toml
└── storage/
    └── apprc.storage.env

# rc.AppRC(..., user_dotenv=rc.UserDotenv(), storage=rc.Storage())
~/.local/share/myapp/
├── apprc.user.env
├── apprc.toml
└── storage/
    └── apprc.storage.env
```

Additional storage names are user-owned registry entries. Their roots may be
anywhere; they do not gain another `storage/<name>/` directory automatically.

> [!IMPORTANT]
> Files on disk never enable application capabilities. Python declarations
> control whether the user dotenv, storage controls, and their write scopes
> exist. Stale files produce doctor warnings and remain eligible for purge.

> [!NOTE]
> For declaration arguments, see
> [docs/References.md#application-declaration](docs/References.md#application-declaration).

<br>

## Runtime Precedence

When dotenv layers are loaded, AppRC merges values in this order:

1. optional packaged `apprc.defaults.env`
2. user `apprc.user.env`, when declared
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

> [!NOTE]
> For the rationale behind layer order and storage selector resolution, see
> [docs/Explanations.md#runtime-bootstrap](docs/Explanations.md#runtime-bootstrap)
> and [docs/Explanations.md#storage-selection](docs/Explanations.md#storage-selection).
> For exact precedence tables, see
> [docs/References.md#runtime-precedence](docs/References.md#runtime-precedence).

<br>

<br>

# Generated Workflows

Mount the generated workflows when you want your application to expose the same
contract to users, setup commands, diagnostics, and the Textual editor.

<br>

## Config CLI

All declarations get read-only inspection and cleanup commands:

```shell
myapp config paths
myapp config doctor
myapp config show
myapp config purge --dry-run
```

Declarations with `rc.UserDotenv()`, `rc.Storage()`, or both also get:

```shell
myapp config setup
myapp config migrate --dry-run
myapp config set KEY VALUE --scope DECLARED_SCOPE
myapp config edit
```

Storage declarations additionally get `--storage NAME_OR_PATH` and:

```shell
myapp config storage add NAME PATH
myapp config storage list
myapp config storage select NAME
myapp config storage rename NAME NEW_NAME
myapp config storage repoint NAME PATH
myapp config storage move NAME PATH
myapp config storage remove NAME
```

The user write scope exists only with `rc.UserDotenv()`. The storage write
scope and storage commands exist only with `rc.Storage()`.

`config edit` requires the optional TUI extra:
`python -m pip install "apprc[tui]"`.

The editor keeps selector errors separate from setup. If a shell variable,
explicit dotenv, or `--storage` value names an unknown storage, the editor
shows the winning source and the `selected_storage` value it overrides. Valid
registry entries remain available. Setup appears only for a missing declared
dotenv or storage marker. A missing registered directory exposes
**Reconnect**, which updates only `apprc.toml`; **Move** remains limited to a
new or empty destination. Opening the editor itself writes nothing.

> [!NOTE]
> For the generated command table, see
> [docs/References.md#generated-cli-commands](docs/References.md#generated-cli-commands).

<br>

## Setup And Diagnostics

Use `config paths` before setup to inspect declared paths without writing. Use
`config setup` or the editor's named setup action to initialize declared files,
then use `config doctor` when a machine is not runnable.

```shell
myapp config paths
myapp config setup --yes --storage-root /absolute/path/to/storage
myapp config doctor
myapp config set access_token secret-value --scope storage
myapp run
```

Setup creates `apprc.user.env` only when the application declares
`rc.UserDotenv()`. For storage applications it registers the initial storage,
records it as `selected_storage`, and creates `apprc.storage.env`. The initial
name is `default` unless an empty registry is opened with a bare
`<APP>_STORAGE` value, in which case setup uses that requested name. No
selector is written to a dotenv file. A custom
`--apprc-dir` applies only to the setup process, so setup prints shell-specific
commands that persist `MYAPP_APPRC_DIR` for later runs.

`config doctor` reports a status such as `storage_not_selected`,
`storage_not_ready`, `user_dotenv_not_ready`,
`storage_registry_not_ready`, or `runnable`.

For optional declarations, a missing user dotenv or absent storage selection
is a warning and the status remains `runnable`. The JSON payload reports
`user_dotenv_required` and `storage_required` so integrations do not have to
infer policy from missing files.

When `CliRuntime(storage_required=True)` reaches a command without a selected
storage, an interactive terminal offers first-use setup with path completion.
A non-interactive terminal writes nothing and prints the exact
`myapp config setup --yes` recovery command.

`config set` changes only the requested dotenv assignment. It preserves
unrelated comments, blank lines, quoting, `export` prefixes, and ordering. If
the key has multiple active assignments, AppRC updates the first and comments
out the later assignments. The interactive CLI and editor require confirmation
before that cleanup. Non-interactive commands write the change and print a
warning afterward.

User-scoped writes require an existing declared `apprc.user.env`; run setup
first. Storage-scoped writes require an initialized selected storage. A
process-environment-only declaration has neither write scope and therefore no
`setup`, `set`, `edit`, or `migrate` command.

AppRC migrates the released 0.19 layout only. Inspect and apply it explicitly:

```shell
myapp config migrate --dry-run
myapp config migrate --yes
```

Migration finds platform-specific 0.19 directories, custom
`MYAPP_APPRC_TOML` locations, `.env.apprc-app`, `.env.apprc-storage`, and
path-valued `MYAPP_STORAGE`. It converts a path selector into the named
`default` storage and removes structural selector keys from the migrated user
dotenv. If a bare selector such as `MYAPP_STORAGE=ontology` is not registered,
interactive migration asks for its existing directory with path completion,
then asks whether to add it or replace an old registry name. Automation must
state the mapping explicitly:

```shell
myapp config migrate --storage-root /existing/ontology --yes
myapp config migrate \
  --storage-root /existing/ontology \
  --replace-storage old-name \
  --yes
```

`--yes` never chooses a replacement. Migration initializes a missing storage
marker but does not move or delete application data. The unreleased
`apprc.app.env` name is intentionally ignored.

Package uninstallers do not remove these user-owned files. Before uninstalling
an AppRC application, run `config purge --dry-run`, review the exact targets,
then run `config purge --yes` if desired. Purge deletes fixed AppRC files and
registered storage roots strictly inside the AppRC directory. For external
storage roots it deletes only `apprc.storage.env` and keeps all other data.
It never follows symlinks and removes the AppRC directory only when empty.

> [!CAUTION]
> A registered internal storage root is application-owned. `config purge`
> recursively deletes that root, including files AppRC did not create. Always
> inspect the dry run first.

> [!IMPORTANT]
> Runtime reads and diagnostics do not create files. `bootstrap`, `config
> paths`, `config doctor`, and opening `config edit` are zero-write. Editor
> actions such as setup, `New`, and `Register` write only after confirmation.
> For storage-backed applications, bootstrap requires the selected root to
> exist and be a directory. Run `config setup` for a missing marker. If a
> registered directory was moved manually, reconnect it with `config storage
> repoint NAME /existing/path`; setup does not recreate it.

> [!NOTE]
> For doctor troubleshooting, see
> [docs/How-To-User-Guides.md#troubleshoot-config-doctor](docs/How-To-User-Guides.md#troubleshoot-config-doctor).
> For exact status names, see
> [docs/References.md#doctor-statuses](docs/References.md#doctor-statuses).

<br>

# More Documentation

The README stays short. The detailed manual and maintainer workflow live in
the documentation directory.

<br>

## Detailed Manual

The detailed manual starts at [docs/README.md](docs/README.md).

> [!NOTE]
> Use [docs/How-To-User-Guides.md](docs/How-To-User-Guides.md) for integration
> recipes, [docs/Explanations.md](docs/Explanations.md) for the AppRC system
> model, [docs/References.md](docs/References.md) for exact commands, files,
> and APIs, and [docs/Development.md](docs/Development.md) for maintainer
> workflow and docs rules.

The repository also ships runnable example CLIs in
[examples/example_apps](examples/example_apps). Each example is its own
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

> [!NOTE]
> For maintainer workflow, documentation rules, and verification commands, see
> [docs/Development.md](docs/Development.md).
