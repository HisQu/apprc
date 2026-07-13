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
4. [How AppRC Works](#how-apprc-works)
   1. [Mental Model](#mental-model)
   2. [Capability Layers](#capability-layers)
   3. [Runtime Precedence](#runtime-precedence)
5. [Generated Workflows](#generated-workflows)
   1. [Config CLI](#config-cli)
   2. [Setup And Diagnostics](#setup-and-diagnostics)
6. [More Documentation](#more-documentation)
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
  --mode storage-only \
  --app-name myapp \
  --display-name "My App" \
  --storage-env-key MYAPP_STORAGE \
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
from pathlib import Path

import typer
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
class MyAppConfig:
    app: AppSettings
    resources: PackageResources
```

Add packaged defaults in `myapp/config/.env.shared`:

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

`rc.field("ENV_KEY")` is required when no default is provided.
`rc.field("ENV_KEY", default="x")` and `default_factory=...` are optional.
`secret=True` redacts display output; it does not encrypt values, store them
elsewhere, or imply that the field is required.

Run the capability examples from a checkout with:

```bash
python -m pip install -e examples/example_apps --no-build-isolation
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
apprc-storage-only config doctor
apprc-examples-run-all
```

They cover `env_only`, `storage_only`, `app_wide_config`,
`app_wide_storage`, named storage, explicit env-file selector precedence, and
the `CliRuntime` app-callback integration. With direnv, `.envrc` sources
[.env.example_apps](.env.example_apps) and bootstraps
`examples/example_app_disk_files/` automatically. Without direnv, source
`.env.example_apps` and run the bootstrap command above once. The generated
directory contains `.apprc-example*/` sandboxes plus commented app-wide,
storage-local, and TOML files showing where the same files would live for a
real app.

> [!NOTE]
> For the step-by-step integration guide, see
> [docs/How-To-User-Guides.md#2-integrate-apprc](docs/How-To-User-Guides.md#2-integrate-apprc).
> For the exact import surface, see
> [docs/References.md#public-interfaces](docs/References.md#public-interfaces).

<br>

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
| Bootstrap | A startup step that merges dotenv layers into this Python process. |
| Generated CLI | A reusable Typer `config` command group for inspection and edits. |
| Editor | A Textual view over the same sections, fields, and dotenv layers. |

> [!NOTE]
> For the deeper architecture behind registered sections, fields, capability layers,
> provenance, and the zero-write policy, see
> [docs/Explanations.md#3-runtime-config-model](docs/Explanations.md#3-runtime-config-model).

<br>

## Capability Layers

Choose one capability constructor:

| Constructor | Storage root | App-wide dotenv | Named storage index |
| --- | --- | --- | --- |
| `rc.AppRC.env_only(...)` | disabled | optional | disabled |
| `rc.AppRC.storage_only(...)` | required | optional | optional |
| `rc.AppRC.app_wide_config(...)` | disabled | default | disabled |
| `rc.AppRC.app_wide_storage(...)` | required | default | optional |

AppRC-managed persistence files are explicit:

| Layer | Default location | Created by |
| --- | --- | --- |
| Packaged shared defaults | package `.env.shared` | the application package |
| App-wide config | platform config home `.env.apprc-app` | `config app init`, app-wide setup, or app-scope save |
| Storage config | `<storage-root>/.env.apprc-storage` | storage setup, `config storage add`, or storage-scope save |
| Named-storage index | `<config-home>/<app>.apprc.toml` | `config storage add/remove` |

> [!NOTE]
> For constructor arguments and capability details, see
> [docs/References.md#capability-constructors](docs/References.md#capability-constructors).

<br>

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

1. CLI `--storage`
2. shell env, for example `MYAPP_STORAGE`
3. explicit env files, respecting `--env-file-overrides-os-environ`
4. app-wide `.env.apprc-app`, when active
5. packaged `.env.shared`

Path selectors work without a named-storage index. Bare named selectors use
`<app>.apprc.toml` when the index exists.

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

`config edit` requires the optional TUI extra:
`python -m pip install "apprc[tui]"`.

> [!NOTE]
> For the generated command table, see
> [docs/References.md#generated-cli-commands](docs/References.md#generated-cli-commands).

<br>

## Setup And Diagnostics

Use `config paths` before setup to see candidate paths and declared
capabilities without writing anything. Use `config setup` for explicit first
storage setup, then use `config doctor` when a machine is not runnable.

```shell
myapp config paths
myapp config setup --yes --storage-root /absolute/path/to/storage
export MYAPP_STORAGE="/absolute/path/to/storage"
myapp config doctor
myapp config set access_token secret-value --scope storage
myapp run
```

`config doctor` reports a status such as `env_not_set`, `storage_not_ready`,
`app_config_not_ready`, `named_storage_not_ready`, or `runnable`.

> [!IMPORTANT]
> Runtime reads and diagnostics do not create files. `bootstrap`, `config
> paths`, `config doctor`, and opening `config edit` are zero-write.

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
package, such as `storage_only`, with a `config/` package,
`cli.py`, and packaged `config/.env.shared` defaults so the source tree mirrors
a real app integration. Generated example disk files live outside that source
tree under `examples/example_app_disk_files/`.

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
