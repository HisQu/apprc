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
<a id="apprc-application-runtime-config"></a>

# `AppRC`


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

AppRC provides configuration, installation, and lifecycle management for Python
applications. Declare typed settings, opt into independent resources such as
config or cache, and add the interfaces your users need. When you ship a native
installer, AppRC can also register the command, keep the app's resource locations
across updates, and provide repair and uninstall.

#### Main dependencies:
- **[`typed-settings`]**: Convert and validate typed application settings.
- **[`python-dotenv`]**: Read setting values from dotenv files.
- **[`platformdirs`]**: Resolve native per-user application paths.
- **[`filelock`]**: Serialize persistent configuration and resource operations.


<!-- --- Graphical Abstract  -->

<br>

| ![AppRC setting layers, optional workspaces, and application code](docs/assets/apprc-abstract-configuration-overview.svg) |
|:--:|
| **Fig. 1 - Graphical Abstract:** AppRC resolves typed settings from layered sources, applies optional workspace overrides, and shares one declaration across application code and configuration tools. |

<br>

---


<!-- ====================================================================== -->
<!-- == Reader journeys -->

| Use the SDK | Ship an application | Use an installed application |
| --- | --- | --- |
| [Install the Python SDK](#installation) and [resolve typed settings](#load-settings). | [Build a release package](#ship-an-application) and [verify installation](docs/How-To-User-Guides.md#validate-installation-on-your-machine). | [Install or register the app](#use-an-installed-application), then [run it](#run-the-application) or [manage it](#maintain-the-application). |

<br>

<!-- ====================================================================== -->
### Table of Contents

1. [AppRC](#project-overview)
2. [Installation](#installation)
   1. [Install the AppRC SDK](#install-the-apprc-sdk)
   2. [Install from a Cloned Repository](#install-from-a-cloned-repository)
   3. [Uninstall](#uninstall)
3. [Usage](#usage)
   1. [Load settings](#load-settings)
   2. [Choose application paths](#choose-application-paths)
   3. [Save user settings](#save-user-settings)
   4. [Add terminal commands](#add-terminal-commands)
   5. [Add a Gradio settings page](#add-a-gradio-settings-page)
4. [Ship an application](#ship-an-application)
5. [Use an installed application](#use-an-installed-application)
   1. [Choose an installation route](#choose-an-installation-route)
   2. [Run the application](#run-the-application)
   3. [Maintain the application](#maintain-the-application)
6. [Documentation](#documentation)

---

<!-- ====================================================================== -->
<br>

# Installation

<br>

<a id="one-line-install"></a>

## Install the AppRC SDK

These SDK packages require Python 3.12 or newer. The examples select the
published 0.36 series. The distribution and lifecycle guides describe AppRC on
`main`. The features available in a downloaded installer depend on the
application release that built it.

| Command | Includes |
| --- | --- |
| `python -m pip install "apprc>=0.36.1,<0.37"` | Core configuration, Typer commands, prompts, and Textual editor. |
| `python -m pip install "apprc-core>=0.36.1,<0.37"` | Configuration and noninteractive path/maintenance APIs. |
| `python -m pip install "apprc-gui>=0.36.1,<0.37"` | Configuration and Gradio settings editor. |

`apprc-core` and `apprc` use `import apprc`; `apprc-gui` provides
`from apprc_gui import ConfigEditor`. Terminal and GUI distributions install the
matching `apprc-core` release.

> [!CAUTION]
> Version 0.32 makes a breaking API and on-disk configuration cutover. Existing
> `Storage`, `storage`, `apprc_dir`, and `--storage` integrations must be changed
> to the new contracts described in the
> [upgrade guide](docs/How-To-User-Guides.md#migrate-existing-applications).
> AppRC does not move, rename, scan, delete, or automatically upgrade old user
> files. Keep any old files as-is and deliberately configure the new paths.

CI runs on Ubuntu: core checks cover Python 3.12, 3.13, and 3.14, and GUI/browser
checks cover Python 3.12. Windows and macOS runtime and installer code remain,
but those platforms are unverified by this CI policy and have
[known native test failures](BACKLOG.md#p2--e1-tooling---windows-and-macos-installation-ci-fails).

<br>

## Install from a Cloned Repository

Follow the [development environment](docs/Development.md#environment) instructions
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

Create one [`AppRC`](docs/Explanations.md#apprc), register
[config sections](docs/Explanations.md#config-sections-and-fields), then build
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
values and validates required fields. Add [dotenv files](docs/How-To-User-Guides.md#load-dotenv-files)
or [packaged defaults](docs/How-To-User-Guides.md#ship-defaults-with-the-application)
when required. [Provenance](docs/Explanations.md#provenance) records which source
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
component. See [path declarations](docs/Explanations.md#application-paths) and
the [path reference](docs/References.md#application-paths).

Managed installers preserve the selected layout in a durable
[installation record](docs/Explanations.md#installation). Reinstallation reuses
that choice; an invocation override does not rewrite it. Single-root groups the
enabled application resource directories, not the Python environment or fixed
native installation support. Plain `pip install -e .` remains independent of
this optional installation workflow.

Applications that need selectable named working directories declare
`Workspaces()`. A [`WorkspaceManager`](docs/Explanations.md#workspaces) manages
the registry and archive operations separately from `AppPaths`; selecting a
workspace does not relocate configuration, cache, or state. `registry=False`
permits direct-directory selection without enabling config. Call
`WorkspaceManager.initialize_workspace(root)` or use `workspace init PATH` to
prepare the workspace dotenv; this writes no config or registry file.

<br>

## Save user settings

`user_dotenv=rc.UserDotenv()` opts into `apprc.user.env` inside the enabled config
directory. `UserDotenv` requires `paths=rc.Paths(config=True)`; it never enables
config implicitly. Obtain a [`ConfigManager`](docs/Explanations.md#configmanager)
with `MyRC.manage()` for settings inspection, setup, and reviewed edits. The
[saved-preference guide](docs/How-To-User-Guides.md#save-a-user-preference)
contains a complete example. Saved secrets use private companion files; the
[secret explanation](docs/Explanations.md#secret-companions) describes their limits.

<br>

## Add terminal commands

Use `rc.cli.mount_app_cli(app, MyRC)` to add configuration and application
maintenance alongside the host's commands. `config` and `workspace` appear when
their capabilities exist; `app paths` and `app doctor` are always available.
`config setup [--adopt] [--yes/-y]` initializes only enabled user configuration.
Installation offers configuration only for missing required user settings without
fallbacks, and skips the offer for non-interactive input.
Setup completion points to `app paths --json` and `app doctor --json`; AppRC
provides descriptions for its generated options in each command's `--help`.
The maintenance group defaults to `app` and can be renamed with
`maintenance_group_name`. The returned mapping identifies actual mounted paths,
such as `app.cache`, for application extensions. See the
[Typer guide](docs/How-To-User-Guides.md#add-configuration-commands-to-typer)
and [command reference](docs/References.md#terminal-commands).

Resource commands are nested under `app`: `app data backup/restore`,
`app cache prune/clear`, and `app state prune/reset` appear only for supported
operations. Declaring a path alone does not enable these commands or create its
directory. `app repair`, `app uninstall`, and `app migrate` require
`installation_management=True`, which also enables editable `app install -e`.
Managed installation uses the native setup executable or an explicit
`installer_entrypoint` callable. There are no resource `init` or `purge` CLI
aliases. Python `ensure_path` and maintenance purge planning remain available
with their existing [ownership and safety boundaries](docs/Explanations.md#maintenance).

The [removal guide](docs/How-To-User-Guides.md#remove-a-managed-program)
covers the uninstall preview, confirmation, and what each option retains.

Passing `launcher_spec` and `launcher_handlers` adds optional root `launch`,
which opens the existing Textual management launcher. It is separate from a
foreground application command and from saved distribution launch support.
Hosts can opt into separated root help panels with
`typer.Typer(cls=rc.cli.AppRCRootGroup)`: host commands and options appear first
in cyan, AppRC panels follow in magenta, and common help/completion options
appear last in a dim panel. Descriptions stay neutral; nested help stays standard.
See [root help and color controls](docs/References.md#root-help-and-runtime-options).

The [Textual editor](docs/Explanations.md#config-editor) and
[Gradio editor](docs/Explanations.md#gradio-editor) edit config settings; when a
workspace registry exists, callers supply the separate `WorkspaceManager`.
Editors do not initialize application state merely by opening.

<br>

## Add a Gradio settings page

Embed `apprc_gui.ConfigEditor(manager)` in an application-owned Gradio `Blocks`.
If the application declares registry-backed workspaces, provide
`workspaces=MyRC.workspaces()` as well. The
[Gradio guide](docs/How-To-User-Guides.md#add-a-gradio-settings-page) shows the
integration.

<!-- ====================================================================== -->
<br>

# Ship an application

<br>

Use the optional [distribution authoring APIs](docs/References.md#distribution-generation)
to build a release package from a committed, locked project snapshot. The
application supplies a build backend. Final executables and `SHA256SUMS` go
in ignored `dist/`. Build intermediates stay in `.cache/apprc/`.

In an opted-in source checkout, the host command provides `dist build` and
`dist check`. Installation management also enables `dist test`. Use `-t` with
build or check for the current platform, and `dist test --managed` for guided
testing of a release installation.
With `AppRCRootGroup`, these commands live under **AppRC: Commands**.

Configure [One-line installer (OLI) generation](docs/How-To-User-Guides.md#generate-one-line-install-scripts)
with `dist build --olis-repo OWNER/REPO` or `RELEASE_REPO_OLIS`. Publish the
installer executables and checksums as application release assets and host the
OLI scripts at a trusted URL. An OLI selects an executable from the
application's latest published GitHub release.

See the [authoring requirements](docs/Development.md#native-application-frontends)
for toolchain prerequisites, application icons, installation messages, and
[configuring the app's default action](docs/Development.md#choose-a-default-action-for-an-installed-command).

<!-- ====================================================================== -->
<br>

# Use an installed application

<br>

## Choose an installation route

The application supplies the release assets, command name, and installation
instructions. Start with the route that matches what you have.

| Route | Where to start | Result |
| --- | --- | --- |
| **One-line installer (OLI)** | [Run the app's published command](docs/How-To-User-Guides.md#run-a-published-installer). It downloads, verifies, and launches the released executable. | Release installation |
| **Released Binary Executable (RBE)** | [Verify and run the binary](docs/How-To-User-Guides.md#run-a-published-installer) from the application's release. | Release installation |
| **Editable Source Checkout (eSC)** | [Prepare and register a checkout](docs/How-To-User-Guides.md#install-from-a-checkout) with `<app> app install -e` in its environment. | Editable installation |
| **Source Build (SB)** | [Build or reuse a local executable](docs/How-To-User-Guides.md#install-from-a-source-build) with `<app> app install` in a distribution-enabled checkout. | Release installation |

Installation reports the applicable steps, resolved paths, and final result.
An application can show a **Next step** after successful setup. On Windows,
double-clicked setup displays its result before asking you to press Enter.

<br>

## Run the application

Use the published command in a terminal or open a shortcut if you asked setup
to make one. If setup changed user PATH, open a new terminal before using the
command. A bare command runs the action chosen by the application. For
example, it may start a local server and open its browser UI. Follow the
[launch guide](docs/How-To-User-Guides.md#run-the-installed-application)
for command publication and shortcuts.

<br>

## Maintain the application

[Run a newer installer](docs/How-To-User-Guides.md#update-an-application) to update
a release installation. Update a registered checkout using Git and uv.
Use the [inspection and repair guide](docs/How-To-User-Guides.md#inspect-or-repair-installation)
to diagnose the saved installation. Review the
[uninstall preview](docs/How-To-User-Guides.md#remove-a-managed-program)
before removing the program and its managed resources.

<!-- ====================================================================== -->
<br>

# Documentation

### Using the project
- [Documentation](docs/README.md) — Start here for component names and learning order.
- [How-to user guides](docs/How-To-User-Guides.md) — Complete specific tasks with independent examples.
- [Examples](docs/EXAMPLES.md) — Choose and run complete application setups, including cache-only.
- [Explanations](docs/Explanations.md) — Understand components and how they connect.
- [References](docs/References.md) — Look up exact APIs, files, commands, and behavior.

### Contributing and maintaining
- [Development](docs/Development.md) — Change, verify, build, and release AppRC.
  - [Development environment](docs/Development.md#environment)
  - [Source ownership](docs/Development.md#source-ownership)
  - [Documentation checks](docs/Development.md#documentation-checks)
  - [README maintenance](docs/Development.md#readme-maintenance)
  - [Verification](docs/Development.md#checks)
  - [Releases](docs/Development.md#release-procedure)
- [Changelog](CHANGELOG.md) — Complete release history and migration requirements.
