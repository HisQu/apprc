# AppRC: Application Runtime Config

[![CI](https://github.com/HisQu/apprc/actions/workflows/ci.yml/badge.svg)](https://github.com/HisQu/apprc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/apprc)](https://pypi.org/project/apprc/)
[![Python](https://img.shields.io/pypi/pyversions/apprc)](https://pypi.org/project/apprc/)
[![License](https://img.shields.io/pypi/l/apprc)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

AppRC gives Python applications typed settings and tools for configuring them.
Define each setting's type, default, and explanation once. Use the same
application declaration to load values, show where they came from, and let users
edit saved overrides.

Applications can also register named data directories outside their source
checkout. Each directory can have its own settings. A config CLI and terminal
editor provide setup, inspection, editing, and storage management.

<!-- Graphical Abstract goes here: -->

| ![Graphical abstract](docs/assets/apprc-abstract-configuration-overview.svg) |
|:--:|
| **Fig. 1 - Graphical Abstract:** AppRC resolves typed settings from layered sources, connects selected storage to its settings and data directory, and shares one declaration across application code and configuration tools. |

- [Install](#install)
- [Load settings](#load-settings)
- [Save user settings](#save-user-settings)
- [Add named storage](#add-named-storage)
- [Add terminal commands](#add-terminal-commands)
- [Add a Gradio settings page](#add-a-gradio-settings-page)
- [Examples and documentation](#examples-and-documentation)

## Install

Python 3.12 or newer is required.

| Command | Includes |
| --- | --- |
| `python -m pip install "apprc>=0.27.0,<0.28"` | Configuration, Typer commands, prompts, and the Textual editor. |
| `python -m pip install "apprc-core>=0.27.0,<0.28"` | Configuration and noninteractive management without terminal dependencies. |
| `python -m pip install "apprc-gui>=0.27.0,<0.28"` | Configuration and a Gradio settings editor. |

`apprc-core` and `apprc` use `import apprc`; `apprc-gui` provides
`from apprc_gui import ConfigEditor`. The terminal and GUI distributions each
install the exact matching `apprc-core` version.

> [!WARNING]
> When upgrading from the previous single-distribution package, use a fresh
> environment or uninstall the old `apprc` first. Follow the
> [migration instructions](docs/How-To-User-Guides.md#migrate-existing-applications)
> for the changed Python API and package ownership.

## Load settings

Create one [`AppRC`](docs/Explanations.md#apprc) for the application and register
its [config sections](docs/Explanations.md#config-sections-and-fields).
This complete example needs no files:

```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field(
        "DEMO_TIMEOUT",
        default=30,
        title="Request timeout",
        explanation_short="Seconds to wait for an API response.",
    )

resolved = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
settings = resolved.build(ClientSettings)
assert settings.timeout == 10
assert settings.provenance_of("timeout").origin == "shell_export_variable"
```

`resolve()` reads the chosen inputs and returns a
[`ResolvedConfig`](docs/Explanations.md#resolvedconfig). `build()` converts those
inputs into the Python values used by `ClientSettings`. Pass `settings` to your
application functions. Omit `environment` to use the actual process environment.

Add [dotenv files](docs/How-To-User-Guides.md#load-dotenv-files) or
[packaged defaults](docs/How-To-User-Guides.md#ship-defaults-with-the-application)
when values should come from files. AppRC applies a defined
[source precedence](docs/References.md#source-precedence), and
[provenance](docs/Explanations.md#provenance) records the source of each field.
Reading configuration creates no files and does not change `os.environ`.
An [importable client](docs/How-To-User-Guides.md#use-apprc-inside-an-importable-client)
can resolve these layers when constructed, so its caller only imports the client.
The [complete client example](docs/EXAMPLES.md#importable-client-with-saved-preferences)
shows the package and its configuration commands.

## Save user settings

Add `user_dotenv=rc.UserDotenv()` to the `AppRC` declaration when users need saved
preferences. The [user dotenv](docs/Explanations.md#user-dotenv-and-the-apprc-directory)
is `apprc.user.env` in the AppRC directory, separate from the installed code.
Its default location for `app_id="demo"` is `~/.local/share/demo`;
`DEMO_APPRC_DIR` relocates it.

[`ConfigManager`](docs/Explanations.md#configmanager), obtained from `MyRC.manage()`,
initializes files and applies reviewed edits. The
[saved-preference guide](docs/How-To-User-Guides.md#save-a-user-preference)
is a complete runnable program. The
[user preferences example](docs/EXAMPLES.md#persistent-user-preferences)
provides the same operations through a CLI.

## Add named storage

Add `storage=rc.Storage()` when the application writes persistent data.
A [storage](docs/Explanations.md#storage) is a registered directory with its own
`apprc.storage.env`. The application obtains the selected root and writes its
data there. Users can keep data outside the source checkout, switch between
named directories, and move or archive them.

The [data-directory guide](docs/How-To-User-Guides.md#store-data-outside-the-source-checkout)
writes a report to selected storage. The
[combined example](docs/EXAMPLES.md#user-settings-and-storage) shows how storage
settings override user preferences. `UserDotenv()` and `Storage()` are independent;
enable either or both.

## Add terminal commands

The [config CLI](docs/Explanations.md#config-cli) adds `config setup`, `config doctor`,
`config set`, `config edit`, and storage commands to a Typer application.
The [Typer guide](docs/How-To-User-Guides.md#add-configuration-commands-to-typer)
shows the entire application and command sequence.

The [config editor](docs/Explanations.md#config-editor) displays configuration
layers together, explains each setting, and edits user or storage overrides.
The same [config fields](docs/Explanations.md#config-sections-and-fields)
also drive the desktop settings view.

## Add a Gradio settings page

Embed `apprc_gui.ConfigEditor` in an application-owned Gradio `Blocks`. Pass it
`MyRC.manage()` so the page can set up declared files, show where effective
values came from, and save user or storage overrides. It opens before required
settings are complete, which makes it suitable for first-run setup. The
[Gradio settings guide](docs/How-To-User-Guides.md#add-a-gradio-settings-page)
shows the connection, and the [secret companion explanation](docs/Explanations.md#secret-companions)
explains where saved `secret=True` fields go.

AppRC does not create installers. The [Windows installer guide](docs/How-To-User-Guides.md#build-a-windows-installer)
shows how an application can package its own launcher and dependencies in one
Setup.exe.

## Examples and documentation

Start with [Documentation](docs/README.md) for the learning order and component names.

| Document | Purpose |
| --- | --- |
| [Explanations](docs/Explanations.md) | Understand the components and their connections. |
| [How-to user guides](docs/How-To-User-Guides.md) | Complete one task using an independent example. |
| [References](docs/References.md) | Look up exact APIs, files, commands, and behavior. |
| [Examples](docs/EXAMPLES.md) | Choose and run a complete application setup. |
| [Development](docs/Development.md) | Change, verify, build, and release AppRC. |
