<!-- README EDITING CONTRACT
Adapt this README in place. Preserve its structure, HTML layout, heading levels,
spacing, and useful content. Replace placeholders and update facts within this
design. Before editing, read "README maintenance" in docs/Development.md.
-->


<!-- ====================================================================== -->
<!-- --- URLs  -->
[`typed-settings`]: https://pypi.org/project/typed-settings/
[`python-dotenv`]: https://pypi.org/project/python-dotenv/
[`platformdirs`]: https://pypi.org/project/platformdirs/
[`filelock`]: https://pypi.org/project/filelock/


<!-- ====================================================================== -->
<!-- == Header -->
<div align="center">


<!-- --- Title  -->
<a id="project-overview"></a>

# `AppRC`: Application Runtime Config


<!-- --- Badges -->

[![CI](https://github.com/HisQu/apprc/actions/workflows/ci.yml/badge.svg)](https://github.com/HisQu/apprc/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/apprc)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/apprc)](https://pypi.org/project/apprc/)
[![PyPI](https://img.shields.io/pypi/v/apprc)](https://pypi.org/project/apprc/)


[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pyright](https://img.shields.io/badge/type%20checked-pyright-blue)](https://microsoft.github.io/pyright/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC)](https://docs.pytest.org/)


</div>


<!-- --- Abstract  -->

AppRC provides typed application settings, optional user preferences, and
independent application paths. An application opts in to configuration,
application data, cache, and state separately; a cache-only application does not
also acquire configuration files or a workspace registry.


#### Main dependencies:
- **[`typed-settings`]**: Convert and validate typed application settings.
- **[`python-dotenv`]**: Read setting values from dotenv files.
- **[`platformdirs`]**: Resolve native per-user application paths.
- **[`filelock`]**: Serialize persistent configuration and resource operations.


<!-- --- Graphical Abstract  -->

<br>

| ![AppRC setting layers, optional workspaces, and application code](https://raw.githubusercontent.com/HisQu/apprc/main/docs/assets/apprc-abstract-configuration-overview.svg) |
|:--:|
| **Fig. 1 - Graphical Abstract:** AppRC resolves typed settings from layered sources, applies optional workspace overrides, and shares one declaration across application code and configuration tools. |

<br>

---


<!-- ====================================================================== -->
### Table of Contents

1. [`AppRC`: Application Runtime Config](#project-overview)
2. [Installation](#installation)
   1. [One-Line Install](#one-line-install)
   2. [Install from a Cloned Repository](#install-from-a-cloned-repository)
   3. [Uninstall](#uninstall)
3. [Usage](#usage)
   1. [Load settings](#load-settings)
   2. [Choose application paths](#choose-application-paths)
   3. [Save user settings](#save-user-settings)
   4. [Add terminal commands](#add-terminal-commands)
   5. [Add a Gradio settings page](#add-a-gradio-settings-page)
4. [Documentation](#documentation)

---

<!-- ====================================================================== -->
<br>

# Installation

<br>

## One-Line Install

Python 3.12 or newer is required.

| Command | Includes |
| --- | --- |
| `python -m pip install "apprc>=0.30.0,<0.31"` | Core configuration, Typer commands, prompts, and Textual editor. |
| `python -m pip install "apprc-core>=0.30.0,<0.31"` | Configuration and noninteractive path/maintenance APIs. |
| `python -m pip install "apprc-gui>=0.30.0,<0.31"` | Configuration and Gradio settings editor. |

`apprc-core` and `apprc` use `import apprc`; `apprc-gui` provides
`from apprc_gui import ConfigEditor`. Terminal and GUI distributions install the
matching `apprc-core` release.

**Caution**

Version 0.30 makes a breaking API and on-disk configuration cutover. Existing
`Storage`, `storage`, `apprc_dir`, and `--storage` integrations must be changed
to the new contracts described in the
[upgrade guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#migrate-existing-applications).
AppRC does not move, rename, scan, delete, or automatically upgrade old user
files. Keep any old files as-is and deliberately configure the new paths.

<br>

## Install from a Cloned Repository

Follow the [development environment](https://github.com/HisQu/apprc/blob/main/docs/Development.md#environment) instructions
for editable installs of the core and optional terminal/GUI distributions.
Ordinary pip installations do not require uv.

<br>

## Uninstall

Use the same Python environment as for installation. To remove all three
AppRC distributions:

```shell
python -m pip uninstall apprc apprc-gui apprc-core
```

Remove only the distributions you no longer need. Keep `apprc-core` if another
installed application or library depends on it. Package removal does not purge
application configuration, data, cache, state, or workspaces; application-owned
resource maintenance is a separate, explicit operation.


<!-- ====================================================================== -->
<br>

# Usage

<br>

## Load settings

Create one [`AppRC`](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#apprc), register
[config sections](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#config-sections-and-fields), then build
typed settings from a `ResolvedConfig`:

```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

resolved = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
settings = resolved.build(ClientSettings)
assert settings.timeout == 10
```

`resolve()` reads configuration and captures a snapshot; `build()` converts
values and validates required fields. Add [dotenv files](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#load-dotenv-files)
or [packaged defaults](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#ship-defaults-with-the-application)
when required. [Provenance](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#provenance) records which source
supplied each value. Resolution does not write files or alter `os.environ`.

<br>

## Choose application paths

Declare only the managed components the application uses:

```python
import apprc as rc

MyRC = rc.AppRC(
    app_id="demo",
    paths=rc.Paths(cache=True),
    layout=rc.Layout.native(),
)

paths = MyRC.paths()                   # inspect; no filesystem writes
cache_dir = MyRC.ensure_path("cache")  # create privately and record ownership
```

`Paths` independently enables `config`, `appdata`, `cache`, and `state`.
`Layout.native()` uses platform user locations; `Layout.single_root(root)` places
enabled categories beneath one explicit root. `AppPaths` reports disabled
locations as `None`; `ensure_path(kind)` initializes only the requested
component. See [path declarations](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#application-paths) and
the [path reference](https://github.com/HisQu/apprc/blob/main/docs/References.md#application-paths).

Managed installers preserve the selected layout in a durable
[installation record](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#installation). Reinstallation reuses
that choice; an invocation override does not rewrite it. Single-root groups the
enabled application resource directories, not the Python environment or fixed
native installation support. Plain `pip install -e .` remains independent of
this optional installation workflow.

Applications that need selectable named working directories declare
`Workspaces()`. A [`WorkspaceManager`](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#workspaces) manages
the registry and archive operations separately from `AppPaths`; selecting a
workspace does not relocate configuration, cache, or state. `registry=False`
permits direct-directory selection without enabling config. Call
`WorkspaceManager.initialize_workspace(root)` or use `workspace init PATH` to
prepare the workspace dotenv; this writes no config or registry file.

<br>

## Save user settings

`user_dotenv=rc.UserDotenv()` opts into `apprc.user.env` inside the enabled config
directory. `UserDotenv` requires `paths=rc.Paths(config=True)`; it never enables
config implicitly. Obtain a [`ConfigManager`](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#configmanager)
with `MyRC.manage()` for settings inspection, setup, and reviewed edits. The
[saved-preference guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#save-a-user-preference)
contains a complete example. Saved secrets use private companion files; the
[secret explanation](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#secret-companions) describes their limits.

<br>

## Add terminal commands

Use `rc.cli.mount_app_cli(app, MyRC)` to mount available configuration and
maintenance groups together. The returned subgroup mapping lets an application
add category-specific commands. `paths` and `doctor` are always available;
config, workspace, and category groups appear only when their declared
capabilities exist. The [Typer guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#add-configuration-commands-to-typer)
and [command reference](https://github.com/HisQu/apprc/blob/main/docs/References.md#terminal-commands) document the groups.

The root `purge` command previews or removes explicitly declared AppRC-managed
resources. It validates ownership and exact targets, never recursively removes
unknown files, and never touches workspace payloads or package caches. Providers
are required for application-specific operations. See
[maintenance](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#maintenance) for its safety boundary.

The [Textual editor](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#config-editor) and
[Gradio editor](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#gradio-editor) edit config settings; when a
workspace registry exists, callers supply the separate `WorkspaceManager`.
Editors do not initialize application state merely by opening.

<br>

## Add a Gradio settings page

Embed `apprc_gui.ConfigEditor(manager)` in an application-owned Gradio `Blocks`.
If the application declares registry-backed workspaces, provide
`workspaces=MyRC.workspaces()` as well. The
[Gradio guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#add-a-gradio-settings-page) shows the
integration.

AppRC's optional
[`apprc.distribution`](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md#installed-packages-and-installer-builds)
authoring APIs generate native installation, launch, and uninstall entries.
Applications own their lifecycle payloads, launch actions, and Windows `Setup.exe`
builds.

<!-- ====================================================================== -->
<br>

# Documentation

### Using the project
- [Documentation](https://github.com/HisQu/apprc/blob/main/docs/README.md) — Start here for component names and learning order.
- [How-to user guides](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md) — Complete specific tasks with independent examples.
- [Examples](https://github.com/HisQu/apprc/blob/main/docs/EXAMPLES.md) — Choose and run complete application setups, including cache-only.
- [Explanations](https://github.com/HisQu/apprc/blob/main/docs/Explanations.md) — Understand components and how they connect.
- [References](https://github.com/HisQu/apprc/blob/main/docs/References.md) — Look up exact APIs, files, commands, and behavior.

### Contributing and maintaining
- [Development](https://github.com/HisQu/apprc/blob/main/docs/Development.md) — Change, verify, build, and release AppRC.
  - [Development environment](https://github.com/HisQu/apprc/blob/main/docs/Development.md#environment)
  - [Source ownership](https://github.com/HisQu/apprc/blob/main/docs/Development.md#source-ownership)
  - [Documentation checks](https://github.com/HisQu/apprc/blob/main/docs/Development.md#documentation-checks)
  - [README maintenance](https://github.com/HisQu/apprc/blob/main/docs/Development.md#readme-maintenance)
  - [Verification](https://github.com/HisQu/apprc/blob/main/docs/Development.md#checks)
  - [Releases](https://github.com/HisQu/apprc/blob/main/docs/Development.md#release-procedure)
