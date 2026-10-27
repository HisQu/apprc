# AppRC: Application Runtime Config

[![CI](https://github.com/HisQu/apprc/actions/workflows/ci.yml/badge.svg)](https://github.com/HisQu/apprc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/apprc)](https://pypi.org/project/apprc/)
[![Python](https://img.shields.io/pypi/pyversions/apprc)](https://pypi.org/project/apprc/)
[![License](https://img.shields.io/pypi/l/apprc)](LICENSE)

AppRC provides typed application settings, optional user preferences, and
independent application paths. An application opts in to configuration,
application data, cache, and state separately; a cache-only application does not
also acquire configuration files or a workspace registry.

- [Install](#install)
- [Load settings](#load-settings)
- [Choose application paths](#choose-application-paths)
- [Save user settings](#save-user-settings)
- [Add terminal commands](#add-terminal-commands)
- [Add a Gradio settings page](#add-a-gradio-settings-page)
- [Examples and documentation](#examples-and-documentation)

## Install

Python 3.12 or newer is required.

| Command | Includes |
| --- | --- |
| `python -m pip install "apprc>=0.30.0,<0.31"` | Core configuration, Typer commands, prompts, and Textual editor. |
| `python -m pip install "apprc-core>=0.30.0,<0.31"` | Configuration and noninteractive path/maintenance APIs. |
| `python -m pip install "apprc-gui>=0.30.0,<0.31"` | Configuration and Gradio settings editor. |

`apprc-core` and `apprc` use `import apprc`; `apprc-gui` provides
`from apprc_gui import ConfigEditor`. Terminal and GUI distributions install the
matching `apprc-core` release.

> [!CAUTION]
> Version 0.30 makes a breaking API and on-disk configuration cutover. Existing
> `Storage`, `storage`, `apprc_dir`, and `--storage` integrations must be changed
> to the new contracts described in the
> [upgrade guide](docs/How-To-User-Guides.md#migrate-existing-applications).
> AppRC does not move, rename, scan, delete, or automatically upgrade old user
> files. Keep any old files as-is and deliberately configure the new paths.

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

Applications that need selectable named working directories declare
`Workspaces()`. A [`WorkspaceManager`](docs/Explanations.md#workspaces) manages
the registry and archive operations separately from `AppPaths`; selecting a
workspace does not relocate configuration, cache, or state. `registry=False`
permits direct-directory selection without enabling config. Call
`WorkspaceManager.initialize_workspace(root)` or use `workspace init PATH` to
prepare the workspace dotenv; this writes no config or registry file.

## Save user settings

`user_dotenv=rc.UserDotenv()` opts into `apprc.user.env` inside the enabled config
directory. `UserDotenv` requires `paths=rc.Paths(config=True)`; it never enables
config implicitly. Obtain a [`ConfigManager`](docs/Explanations.md#configmanager)
with `MyRC.manage()` for settings inspection, setup, and reviewed edits. The
[saved-preference guide](docs/How-To-User-Guides.md#save-a-user-preference)
contains a complete example. Saved secrets use private companion files; the
[secret explanation](docs/Explanations.md#secret-companions) describes their limits.

## Add terminal commands

Use `rc.cli.mount_app_cli(app, MyRC)` to mount available configuration and
maintenance groups together. The returned subgroup mapping lets an application
add category-specific commands. `paths` and `doctor` are always available;
config, workspace, and category groups appear only when their declared
capabilities exist. The [Typer guide](docs/How-To-User-Guides.md#add-configuration-commands-to-typer)
and [command reference](docs/References.md#terminal-commands) document the groups.

The root `purge` command previews or removes explicitly declared AppRC-managed
resources. It validates ownership and exact targets, never recursively removes
unknown files, and never touches workspace payloads or package caches. Providers
are required for application-specific operations. See
[maintenance](docs/Explanations.md#maintenance) for its safety boundary.

The [Textual editor](docs/Explanations.md#config-editor) and
[Gradio editor](docs/Explanations.md#gradio-editor) edit config settings; when a
workspace registry exists, callers supply the separate `WorkspaceManager`.
Editors do not initialize application state merely by opening.

## Add a Gradio settings page

Embed `apprc_gui.ConfigEditor(manager)` in an application-owned Gradio `Blocks`.
If the application declares registry-backed workspaces, provide
`workspaces=MyRC.workspaces()` as well. The
[Gradio guide](docs/How-To-User-Guides.md#add-a-gradio-settings-page) shows the
integration. AppRC does not create installers; applications own their launchers
and Windows `Setup.exe` builds.

## Examples and documentation

Start with [Documentation](docs/README.md) for component names and learning order.

| Document | Purpose |
| --- | --- |
| [Explanations](docs/Explanations.md) | Understand components and how they connect. |
| [How-to user guides](docs/How-To-User-Guides.md) | Complete one task with an independent example. |
| [References](docs/References.md) | Look up exact APIs, files, commands, and behavior. |
| [Examples](docs/EXAMPLES.md) | Choose and run a complete application setup, including cache-only. |
| [Development](docs/Development.md) | Change, verify, build, and release AppRC. |
