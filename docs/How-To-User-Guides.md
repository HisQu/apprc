# How-to user guides

[Documentation](README.md) · [Explanations](Explanations.md) · [References](References.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [Define and load settings](#define-and-load-settings)
  - [Read typed settings](#read-typed-settings)
  - [Declare an API key](#declare-an-api-key)
  - [Load dotenv files](#load-dotenv-files)
  - [Ship defaults with the application](#ship-defaults-with-the-application)
  - [Find where a value came from](#find-where-a-value-came-from)
- [Save preferences](#save-preferences)
  - [Save a user preference](#save-a-user-preference)
  - [Use AppRC inside an importable client](#use-apprc-inside-an-importable-client)
  - [Edit or remove a saved override](#edit-or-remove-a-saved-override)
- [Choose and initialize application paths](#choose-and-initialize-application-paths)
  - [Select a workspace](#select-a-workspace)
  - [Choose a layout from bootstrap inputs](#choose-a-layout-from-bootstrap-inputs)
  - [Supply application maintenance operations](#supply-application-maintenance-operations)
- [Give users configuration tools](#give-users-configuration-tools)
  - [Add configuration commands to Typer](#add-configuration-commands-to-typer)
  - [Preview and apply a purge](#preview-and-apply-a-purge)
  - [Inspect and edit settings in the terminal](#inspect-and-edit-settings-in-the-terminal)
  - [Save and repair secret settings](#save-and-repair-secret-settings)
  - [Add a Gradio settings page](#add-a-gradio-settings-page)
  - [Build a Windows installer](#build-a-windows-installer)
- [Use settings across application code](#use-settings-across-application-code)
  - [Pass several settings sections together](#pass-several-settings-sections-together)
  - [Import settings from a dependency](#import-settings-from-a-dependency)
  - [Reload settings or use temporary overrides](#reload-settings-or-use-temporary-overrides)
  - [Supply settings to environment-only code](#supply-settings-to-environment-only-code)
  - [Generate a config package](#generate-a-config-package)
- [Diagnose and migrate](#diagnose-and-migrate)
  - [Troubleshoot configuration](#troubleshoot-configuration)
  - [Migrate existing applications](#migrate-existing-applications)

Each guide is independent. Install AppRC using the [installation instructions](../README.md#install).
The Python examples run on Python 3.12 or newer. Examples using temporary
directories remove their files when they finish. CLI guides explicitly identify
the files they keep in the working directory.

<br>

# Define and load settings

<a id="integrate-typed-settings"></a>
## Read typed settings

Define a [config section](Explanations.md#config-sections-and-fields), register it
on one [`AppRC`](Explanations.md#apprc), and build its settings from a
[`ResolvedConfig`](Explanations.md#resolvedconfig). Save this as `demo.py` and run
`python demo.py`:

<!-- example-file: demo.py -->
```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)


def request_timeout(settings: ClientSettings) -> int:
    return settings.timeout


resolved = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
settings = resolved.build(ClientSettings)
assert request_timeout(settings) == 10
print(settings.timeout)
```

It prints `10`. The input is a string, but the field annotation makes the
application receive an integer. Passing an explicit environment mapping keeps
this example independent of your shell. Omit `environment` to use process
values. The [minimal setup](EXAMPLES.md#settings-without-managed-files) also shows
how separate resolutions retain their own values.

## Declare an API key

Use a required [config field](References.md#config-fields) with `secret=True`.
The application receives the value; AppRC's display helpers redact it. Save this
as `demo.py` and run `python demo.py`. The example value is a placeholder, not a
credential.

<!-- example-file: demo.py -->
```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    token: str = rc.field(
        "DEMO_TOKEN",
        required=True,
        secret=True,
        title="API token",
        explanation_short="Token used to authenticate API requests.",
        explanation_long="Obtain a token from your API provider and supply DEMO_TOKEN.",
    )

settings = MyRC.resolve(environment={"DEMO_TOKEN": "example-placeholder"}).build(ClientSettings)
assert settings.token == "example-placeholder"
assert settings.provenance_of("token").display_value == "<redacted>"
print(settings.provenance_of("token").display_value)
```

It prints `<redacted>`. Without `DEMO_TOKEN`, `build()` reports a missing required
field. The flag does not encrypt dotenv files or install a credential store.
When displaying [provenance](Explanations.md#provenance), use `display_value`;
`value` and `ResolvedConfig.values` contain actual inputs.

<a id="load-dotenv-inputs"></a>
## Load dotenv files

Pass explicit files in [`ResolveOptions.env_files`](References.md#resolution).
This complete example creates a temporary file and removes it on exit:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

with TemporaryDirectory() as directory:
    path = Path(directory) / "deployment.env"
    path.write_text("DEMO_TIMEOUT=20\n", encoding="utf-8")
    environment = {"DEMO_TIMEOUT": "10"}
    normal = MyRC.resolve(rc.ResolveOptions(env_files=(path,)), environment=environment)
    file_first = MyRC.resolve(
        rc.ResolveOptions(env_files=(path,), env_file_overrides_os_environ=True),
        environment=environment,
    )
    assert normal.build(ClientSettings).timeout == 10
    assert file_first.build(ClientSettings).timeout == 20
    print("environment wins: 10; explicit file wins: 20")
```

Run it with `python demo.py`. By default, the process environment has higher
priority than explicit files. The option above reverses those two priorities.
Later explicit files win over earlier files. The
[layer explanation](Explanations.md#configuration-layers) and
[precedence reference](References.md#source-precedence) describe the other layers.
The [complete CLI example](EXAMPLES.md#explicit-dotenv-precedence) exposes the
same choice as command-line options.

## Ship defaults with the application

Set `config_package` to an importable Python package containing
`apprc.defaults.env`. For a source-run example, create these files in a new
working directory:

```text
working-directory/
  demo.py
  demo_config/
    __init__.py
    apprc.defaults.env
```

`demo_config/__init__.py`:

<!-- example-file: demo_config/__init__.py -->
```python
"""Packaged defaults for the example."""
```

`demo_config/apprc.defaults.env`:

<!-- example-file: demo_config/apprc.defaults.env -->
```dotenv
DEMO_TIMEOUT=20
```

`demo.py`:

<!-- example-file: demo.py -->
```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo", config_package="demo_config")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

settings = MyRC.resolve(environment={}).build(ClientSettings)
assert settings.timeout == 20
assert settings.provenance_of("timeout").resource == ("demo_config", "apprc.defaults.env")
print(settings.timeout)
```

Run `python demo.py` from that directory. It prints `20`: the packaged default
replaces the Python fallback. When distributing your app, include the dotenv
file as package data. For setuptools, this fragment belongs in the application's
`pyproject.toml`:

```toml
[tool.setuptools.package-data]
demo_config = ["apprc.defaults.env"]
```

The existing [precedence example package](../examples/example_apps/src/explicit_env_precedence/config/apprc.defaults.env)
contains a real packaged file. Missing optional packaged defaults contribute no
values, but an unimportable `config_package` is an error. Archive resources retain
[package provenance](References.md#provenance-and-lifecycle) after loading.

## Find where a value came from

Call [`provenance_of()`](References.md#provenance-and-lifecycle) on the settings
object. The argument is the Python field name, not its environment key. Run this
complete `demo.py`:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

with TemporaryDirectory() as directory:
    path = Path(directory) / "deployment.env"
    path.write_text("DEMO_TIMEOUT=20\n", encoding="utf-8")
    settings = MyRC.resolve(rc.ResolveOptions(env_files=(path,)), environment={}).build(ClientSettings)
    origin = settings.provenance_of("timeout")
    assert origin.origin == "shell_dotenv_explicit"
    assert origin.path == path
    assert origin.display_value == 20
    print(origin.origin)
```

It prints `shell_dotenv_explicit`. [Provenance](Explanations.md#provenance) also
records Python defaults and overrides. The [config editor](Explanations.md#config-editor)
lets users compare source values without writing Python inspection code.

<br>

# Save preferences

<a id="set-up-persistence"></a>
## Save a user preference

Enable a [user dotenv](Explanations.md#user-dotenv) together with the config
component. This example uses a temporary single-root layout:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    MyRC = rc.AppRC(
        app_id="demo",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(Path(directory)),
        user_dotenv=rc.UserDotenv(),
    )

    @MyRC.config("client", prefix="DEMO_")
    class ClientSettings(rc.Config):
        timeout: int = rc.field("DEMO_TIMEOUT", default=30)

    manager = MyRC.manage(environment={})
    manager.setup()
    manager.apply_edit(manager.plan_update("client.timeout", "20", scope="user"))
    config_dir = MyRC.paths().require("config")
    assert (config_dir / "apprc.user.env").is_file()
    assert manager.resolve().build(ClientSettings).timeout == 20
    print("saved timeout: 20")
```

`UserDotenv()` does not enable config; `Paths(config=True)` declares that
component. `setup()` initializes only user configuration. The user dotenv path
comes from the resolved config directory, not a separate `apprc_dir` override.
Reading settings does not create a missing dotenv.

<a id="edit-saved-values"></a>
## Use AppRC inside an importable client

A library can own its [`AppRC`](Explanations.md#apprc) declaration and load
settings when a client is constructed. Its caller then imports `Client` and does
not need to declare AppRC or call a setup function. This example uses a
[config section](Explanations.md#config-sections-and-fields), packaged defaults,
and a [user dotenv](Explanations.md#user-dotenv).

Create these files in one working directory:

```text
working-directory/
  demo.py
  myclient/
    __init__.py
    client.py
    config.py
    apprc.defaults.env
```

`myclient/__init__.py`:

<!-- example-file: myclient/__init__.py -->
```python
"""Public imports for the example client."""

from myclient.client import Client
```

`myclient/config.py`:

<!-- example-file: myclient/config.py -->
```python
import apprc as rc

MyRC = rc.AppRC(
    app_id="demo",
    config_package="myclient",
    paths=rc.Paths(config=True),
    bootstrap_env_prefix="DEMO",
    user_dotenv=rc.UserDotenv(),
)


@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)
```

`myclient/apprc.defaults.env`:

<!-- example-file: myclient/apprc.defaults.env -->
```dotenv
DEMO_TIMEOUT=20
```

`myclient/client.py`:

<!-- example-file: myclient/client.py -->
```python
from myclient.config import ClientSettings, MyRC

class Client:
    def __init__(self, settings: ClientSettings | None = None) -> None:
        self.settings = settings if settings is not None else MyRC.resolve().build(ClientSettings)

    @property
    def timeout(self) -> int:
        return self.settings.timeout
```

`demo.py` creates a disposable user dotenv so the example does not touch your
normal AppRC directory. The only import needed for ordinary client use is
`Client`:

<!-- example-file: demo.py -->
```python
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from myclient import Client

with TemporaryDirectory() as directory:
    os.environ["DEMO_LAYOUT"] = "single-root"
    os.environ["DEMO_ROOT"] = directory
    config_dir = Path(directory) / "config"
    config_dir.mkdir()
    (config_dir / "apprc.user.env").write_text("DEMO_TIMEOUT=15\n", encoding="utf-8")
    assert Client().timeout == 15

    os.environ["DEMO_TIMEOUT"] = "10"
    assert Client().timeout == 10
    print("user: 15; process: 10")
```

Run `python demo.py`. The demonstration script writes `apprc.user.env`; importing
or constructing `Client` does not write it. Each construction calls
[`resolve().build()`](References.md#resolution), so a new client sees a changed
user dotenv while an existing client keeps its settings. The process value wins
over the file values. Pass an already built `ClientSettings` to share one
[`ResolvedConfig`](Explanations.md#resolvedconfig) across clients or to inject
settings in a test. Include `apprc.defaults.env` as package data when building
a wheel, as shown in [Ship defaults with the application](#ship-defaults-with-the-application).
The [complete importable-client example](EXAMPLES.md#importable-client-with-saved-preferences)
also provides configuration commands for users.

## Edit or remove a saved override

An edit plan identifies the target file and proposed assignment. A preview
shows the effective configuration after that edit, including higher-priority
values that might still win. Run this independent `demo.py`:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    MyRC = rc.AppRC(
        app_id="demo",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(Path(directory)),
        user_dotenv=rc.UserDotenv(),
    )

    @MyRC.config("client", prefix="DEMO_")
    class ClientSettings(rc.Config):
        timeout: int = rc.field("DEMO_TIMEOUT", default=30)

    manager = MyRC.manage(environment={})
    manager.setup()
    plan = manager.plan_update("client.timeout", "20", scope="user")
    preview = manager.preview_edit(plan)
    assert preview.ready
    manager.apply_edit(plan)
    assert manager.resolve().build(ClientSettings).timeout == 20
    removal = manager.plan_removal("client.timeout", scope="user")
    assert removal is not None
    manager.apply_edit(removal)
    assert manager.resolve().build(ClientSettings).timeout == 30
    print("removed override; timeout is 30 again")
```

Removing the saved assignment restores the next value in
[source precedence](References.md#source-precedence). Edits preserve unrelated
comments and formatting. Duplicate assignments are reported for cleanup.

`apply_edit()` raises [`StaleEditError`](References.md#errors-and-write-guarantees)
if the target file changed after planning. Inspect again and create a new plan;
do not retry the old one. Explicit `scope="user"` can create a missing user
dotenv. Workspace edits require a selected workspace. The
[user/workspace setup](EXAMPLES.md#user-preferences-and-workspaces) demonstrates both scopes.

<br>

# Choose and initialize application paths

Declare the components the application actually uses. This complete `demo.py`
uses only cache and writes no files until `ensure_path()` is called:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    MyRC = rc.AppRC(
        app_id="cache-demo",
        paths=rc.Paths(cache=True),
        layout=rc.Layout.single_root(Path(directory)),
    )
    inspected = MyRC.paths()
    assert inspected.config_dir is None
    assert inspected.cache_dir == Path(directory) / "cache"
    assert not inspected.cache_dir.exists()
    cache_dir = MyRC.ensure_path("cache")
    assert cache_dir.is_dir()
    assert (cache_dir / ".apprc-owner.json").is_file()
    assert not (Path(directory) / "config").exists()
    print("only cache initialized")
```

`Paths` enables config, appdata, cache, and state separately. `AppPaths` returns
absolute paths for enabled components and `None` for disabled components.
`paths()` is zero-write; `ensure_path(kind)` creates only the requested
component and records ownership. See the [component explanation](Explanations.md#application-paths)
and [API reference](References.md#application-paths).

For native locations use `Layout.native()`. To colocate enabled roots use
`Layout.single_root(root)`, which resolves the root against invocation current
working directory. `ensure_path("state")` does not create logs; use
`ensure_path("logs")` to initialize the subordinate log path.

If a category root already contains files without an owner marker, the safe
default is refusal. `ensure_path("config", adopt=True)` explicitly adopts a
nonempty unowned config root without moving or deleting its contents. `config
init --adopt` provides the same explicit choice through the CLI. Do not use
adoption to make AppRC claim files you do not control.

## Select a workspace

Declare `Workspaces()` when users need named working directories. This complete
script demonstrates registration and selection; the registry is in the enabled
config root, while the workspace payload is separate:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    root = Path(directory)
    MyRC = rc.AppRC(
        app_id="demo",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(root / "app"),
        workspaces=rc.Workspaces(),
    )
    MyRC.ensure_path("config")
    manager = MyRC.workspaces(environment={})
    manager.register_workspace("work", root / "work")
    manager.select_workspace("work")
    before = MyRC.resolve(environment={})
    assert before.workspace is not None
    assert before.workspace.workspace_name == "work"
    assert before.paths.config_dir == root / "app" / "config"
    print(before.workspace.root)
```

Selection changes the workspace settings overlay and root, not the captured
`AppPaths`. `WorkspaceManager` owns registration, selection, rename, repoint,
move, remove, archive, and restore. Unregistering never deletes workspace
payloads. The [workspace reference](References.md#workspace-selection) defines
selector precedence and direct paths.

`Workspaces(registry=False)` permits direct path selection without config or a
registry. Relative paths resolve against invocation current working directory;
a bare value supplied as a workspace selector fails because names require a
registry. The explicit `WorkspaceManager.initialize_workspace(root)` path
argument may be any relative path, including `Path("demo-workspace")`. Initialize
the directory before selecting it. This creates `apprc.workspace.env` in the
root, without config or registry writes; the secret companion is created only
if needed. The direct mode does not persist named registration:

```python
from pathlib import Path
import apprc as rc

MyRC = rc.AppRC(
    app_id="demo",
    workspaces=rc.Workspaces(registry=False),
)
manager = MyRC.workspaces(environment={})
root = Path("demo-workspace")
manager.initialize_workspace(root)
selected_root = manager.select_workspace("./demo-workspace")
assert selected_root == root.resolve()
```

Run the CLI form with:

```shell
python demo.py workspace init ./demo-workspace
python demo.py workspace info ./demo-workspace
```

The CLI exposes the same setup and inspection as `workspace init PATH` and
`workspace info PATH`. Both take an explicit root path; they do not enable config
or write a registry. Registry-backed workspaces continue to use named
registration and selection.

## Choose a layout from bootstrap inputs

With `bootstrap_env_prefix="DEMO"` the bootstrap pair is `DEMO_LAYOUT` and
`DEMO_ROOT`. AppRC selects both values from one winning raw layer: root alone
means single-root; `native` plus a root in that same layer is invalid; a higher
layer's `native` ignores a lower layer's root. Invocation `Layout` overrides
these inputs. Explicit dotenv files are separate layers, and their ordering
relative to process environment follows `env_file_overrides_os_environ`.
`AppPaths.source` records which layer supplied the chosen layout.

## Supply application maintenance operations

AppRC can describe basic information for each enabled path, but application
backup, restore, cache pruning, state reset, and semantic purge require an
explicit provider handler. Supply `MaintenanceHandlers` to
`MyRC.maintain(...)` and to the CLI mount. Commands for absent operations are
not mounted. An app-specific provider owns its database format, leases, and
coordination; AppRC validates ownership, boundaries, exact target lists, and
plan revisions before dispatch.

Purge is not recursive cleanup. It previews exact AppRC-managed files and empty
directories, refuses unknown contents and unsafe links, and reports partial
results. It never includes workspace payloads or package caches, and multiple
roots are not deleted atomically. See [maintenance contracts](References.md#maintenance).
<br>

# Give users configuration tools

<a id="integrate-a-terminal-application"></a>
## Add configuration commands to Typer

`mount_app_cli` provides the high-level integration: it owns the Typer callback,
captures bootstrap options, and puts the resolved snapshot in CLI state. This
complete `demo.py` configures user preferences and a single-root layout:

<!-- example-file: demo.py -->
```python
import apprc as rc
import typer

MyRC = rc.AppRC(
    app_id="demo",
    paths=rc.Paths(config=True),
    layout=rc.Layout.single_root("demo-config"),
    user_dotenv=rc.UserDotenv(),
)

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

app = typer.Typer()
rc.cli.mount_app_cli(app, MyRC)

@app.command()
def run(ctx: typer.Context) -> None:
    state = rc.cli.state_from(ctx, rc.cli.DefaultConfigCliState)
    assert state.resolved is not None
    typer.echo(state.resolved.build(ClientSettings).timeout)

if __name__ == "__main__":
    app()
```

Run from the directory containing `demo.py`:

```shell
python demo.py --help
python demo.py paths config
python demo.py config init
python demo.py config setup --yes
python demo.py config set client.timeout 20 --scope user
python demo.py run
python demo.py doctor --json
```

`paths config` prints its absolute path without creating it. `config init`
initializes the config category and its owner marker. The edit is saved in
`demo-config/config/apprc.user.env`; `run` then prints `20`. A high-level mount
rejects an existing root callback. If the application already owns that
callback, use `CliRuntime`'s `mount_app_groups()` method and call
`CliRuntime.prepare()` in the callback. See the
[callback example](EXAMPLES.md#an-application-owned-cli-callback).

## Preview and apply a purge

`paths` reports locations and existence; `doctor` reports configuration and
declared-path diagnostics. The root `purge` previews exact files and empty
directories; it is not a recursive application-data cleaner. For a cache-only
app with `Paths(cache=True)`, the maintenance commands work without config,
registry, or application state setup:

```shell
demo paths --json
demo doctor --json
demo purge --scope cache --dry-run --json
demo purge --scope cache --yes --json
```

`purge` requires `--scope CATEGORY` one or more times, or `--all`, but not both.
Disabled explicit categories are invalid; `--all` expands only declared
components and succeeds as a no-op when none are declared. JSON output contains
`plans` and `results`; preview results are empty. A JSON apply prompt goes to
stderr. Noninteractive apply requires `--yes`/`-y`. Exit status is 0 for
success/preview, 1 for cancellation or partial/failure, and 2 for invalid or
unsafe preflight. Unknown files, unsafe links, changed revisions, or unowned
nonempty roots are not deleted. Applications provide handlers for their own
backup, restore, pruning, reset, or purge semantics; commands without handlers
are absent. See the [maintenance reference](References.md#maintenance).

## Inspect and edit settings in the terminal

Use the [user preferences example](EXAMPLES.md#persistent-user-preferences) to
try the Textual editor. The editor can show defaults, explicit files, and
environment values beside saved overrides. A higher-priority process value can
still win after a successful file edit. Workspace browsing is independent of
the saved selected workspace; see the [editor explanation](Explanations.md#config-editor).

Opening the editor creates no files. Setup and save actions call
`ConfigManager`; workspace selection and registry operations use
`WorkspaceManager`.

## Save and repair secret settings

Mark a [config field](Explanations.md#config-sections-and-fields) with
`secret=True` to redact display output and route managed writes to a private
companion. This example uses the config layer and selected workspace layer:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    root = Path(directory)
    MyRC = rc.AppRC(
        app_id="demo",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(root / "app"),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(),
    )

    @MyRC.config("client", prefix="DEMO_")
    class ClientSettings(rc.Config):
        token: str = rc.field("DEMO_TOKEN", default="", secret=True)

    MyRC.ensure_path("config")
    workspaces = MyRC.workspaces(environment={})
    workspaces.register_workspace("work", root / "work")
    workspaces.select_workspace("work")
    manager = MyRC.manage(environment={})
    manager.setup()
    manager.apply_edit(manager.plan_update("DEMO_TOKEN", "user-example", scope="user"))
    manager.apply_edit(manager.plan_update("DEMO_TOKEN", "workspace-example", scope="workspace"))
    assert manager.writable_path("user", secret=True).name == "apprc.user.secret.env"
    assert manager.writable_path("workspace", secret=True).name == "apprc.workspace.secret.env"
    assert manager.resolve().build(ClientSettings).token == "workspace-example"
```

The current secret migration/repair commands concern secret assignments only;
they do not migrate old layout or registry formats. Inspect `config secrets
status` before explicitly migrating existing secrets. Do not rename old storage
files to the new workspace filenames.

## Add a Gradio settings page

Install `apprc-gui` alongside the application. The editor receives a
`ConfigManager`; provide a separate `WorkspaceManager` when registry-backed
workspace controls are needed:

```python
import gradio as gr
from apprc_gui import ConfigEditor

from my_app.config import MyRC

manager = MyRC.manage()
workspaces = MyRC.workspaces()  # only when Workspaces(registry=True) is declared
with gr.Blocks() as page:
    gr.Markdown("# My App")
    with gr.Tab("Settings"):
        ConfigEditor(manager, workspaces=workspaces).render()

page.launch(server_name="127.0.0.1", share=False)
```

Config-only applications can pass just `manager`. Registry-backed workspace
controls without a manager fail clearly rather than silently disappearing.
The application owns the start callback and builds its runtime only after
`manager.inspect().ready`.


## Build a Windows installer

The application owns its [installer build](Explanations.md#installed-packages-and-installer-builds).
Declare the browser launcher and CLI entry points in `pyproject.toml`:

```toml
[project]
dependencies = ["apprc-gui>=0.27.0,<0.28", "gradio>=6.26,<7"]

[project.gui-scripts]
my-app-desktop = "my_app.desktop:main"

[project.scripts]
my-app = "my_app.cli:main"

```

For a one-file offline Windows installer, build wheels for the locked
application and its dependencies on Windows. `uv export --locked
--no-emit-project --no-dev --no-hashes -o requirements.txt` produces a pinned
input for `python -m pip wheel --no-deps -r requirements.txt -w wheelhouse`;
build the application wheel into the same directory. Include those wheels, a
Python runtime, and `uv.exe` in an [Inno Setup](https://jrsoftware.org/isinfo.php)
payload. During setup, create an application-owned environment and install
the wheels with `uv pip install --offline --no-index --no-deps`. Point the
Start menu shortcut at `pythonw.exe -m my_app.desktop`. Test packaged
resources, first-run setup, browser launch, and upgrade on a Windows account
without Python or network access. AppRC supplies the editor and file rules;
the application owns its installer and entry points.

<br>

# Use settings across application code

<a id="compose-a-bundle"></a>
## Pass several settings sections together

A [config bundle](Explanations.md#config-bundles) is a dataclass containing config
sections. Use it when your application needs to pass several sections together.
This complete `demo.py` defines a client section and an output section:

<!-- example-file: demo.py -->
```python
from dataclasses import dataclass, field
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

@MyRC.config("output", prefix="DEMO_")
class OutputSettings(rc.Config):
    format: str = rc.field("DEMO_FORMAT", default="json", choices=("json", "csv"))

@MyRC.bundle
@dataclass(kw_only=True)
class ApplicationConfig:
    client: ClientSettings = field(default_factory=ClientSettings)
    output: OutputSettings = field(default_factory=OutputSettings)


def run(config: ApplicationConfig) -> str:
    return f"{config.output.format}: timeout={config.client.timeout}"


config = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"}).build(ApplicationConfig)
assert run(config) == "json: timeout=10"
print(run(config))
```

AppRC constructs both registered sections from the same `ResolvedConfig`.
You can still build and pass a single section separately. The
[bundle reference](References.md#config-bundles) explains custom factory behavior;
the [larger example](EXAMPLES.md#several-sections-and-temporary-overrides)
adds temporary overrides and reloads.

## Import settings from a dependency

Use an [imported config binding](Explanations.md#imported-dependency-settings)
when a host application wants its own names and defaults for selected
dependency settings. The host declares every parent field and maps each selected
dependency field to one of them; omitted dependency fields keep their Python
defaults. This complete `demo.py` maps two dependency model fields to the same
parent field, then builds the dependency section both directly and inside
a [config bundle](Explanations.md#config-bundles):

<!-- example-file: demo.py -->
```python
from dataclasses import dataclass, field
import apprc as rc

DependencyRC = rc.AppRC(app_id="dependency")

@DependencyRC.config("client", prefix="DEP_")
class DependencyClient(rc.Config):
    api_key: str = rc.field("DEP_API_KEY", secret=True)
    base_url: str = rc.field("DEP_BASE_URL", default="https://dependency.example")
    model_llm: str = rc.field("DEP_MODEL_LLM", default="dependency-model")
    model_fast: str = rc.field("DEP_MODEL_FAST", default="dependency-model")

HostRC = rc.AppRC(app_id="host")
host_client = HostRC.import_dependency_config(
    DependencyRC,
    DependencyClient,
    key="client",
    prefix="HOST_LLM_",
    title="Host language model",
    fields={
        "api_key": rc.field("HOST_LLM_API_KEY", secret=True),
        "endpoint": rc.field(
            "HOST_LLM_ENDPOINT", default="https://host.example"
        ),
        "model": rc.field("HOST_LLM_MODEL", default="host-model"),
    },
    field_targets={
        "api_key": "api_key",
        "base_url": "endpoint",
        "model_llm": "model",
        "model_fast": "model",
    },
)

@HostRC.bundle
@dataclass(kw_only=True)
class HostSettings:
    client: DependencyClient = field(default_factory=DependencyClient)

resolved = HostRC.resolve(
    environment={
        "HOST_LLM_API_KEY": "example-placeholder",
        "HOST_LLM_MODEL": "host-model-v2",
        "DEP_BASE_URL": "https://ignored.example",
    }
)
bundle = resolved.build(HostSettings)
client = resolved.build(host_client)

assert bundle.client.base_url == "https://host.example"
assert bundle.client.model_llm == bundle.client.model_fast == "host-model-v2"
assert client.provenance_of("api_key").env_key == "HOST_LLM_API_KEY"
assert "example-placeholder" not in repr(client)
print(f"{bundle.client.base_url}: {bundle.client.model_llm}")
```

Run it with `python demo.py`. The dependency's `DEP_BASE_URL` input is ignored
because the host resolves this section from its own namespace. The dependency's
user and workspace files are also excluded, as are its layout bootstrap keys.
Parent fields determine editor and doctor metadata, and a parent secret field
cannot weaken a secret declared by the dependency. The
[API reference](References.md#dependency-config-imports) documents field-map
validation, packaged-default opt-in, and snapshot behavior.

If an imported dependency section requires a workspace, the host declares
`workspaces=rc.Workspaces()` and selects a valid parent workspace before
building it. The parent's workspace layer can supply mapped settings; the
dependency's selector, registry, and files remain excluded. The host supplies
any workspace path the dependency needs through its normal integration API.

<a id="reload-and-export"></a>
## Reload settings or use temporary overrides

Use a scoped copy for one operation, and `reload_from()` to apply newly resolved
values. This script shows which objects change:

<!-- example-file: demo.py -->
```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

settings = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"}).build(ClientSettings)
quick = settings.scoped(timeout=5)
assert settings.timeout == 10
assert quick.timeout == 5
next_run = MyRC.resolve(environment={"DEMO_TIMEOUT": "20"})
settings.reload_from(next_run)
quick.reload_from(next_run)
assert settings.timeout == 20
assert quick.timeout == 5
quick.reload_from(next_run, override_python_values=True)
assert quick.timeout == 20
print("reloaded settings; explicit override replaced only when requested")
```

A reload validates new values before changing the object. If validation fails,
its previous values and [provenance](Explanations.md#provenance) remain intact.
`reload()` without a `ResolvedConfig` reads the live process environment; use
`reload_from()` for managed files. The [lifecycle reference](References.md#provenance-and-lifecycle)
also covers copies and assignments.

## Supply settings to environment-only code

Some dependencies read environment variables themselves and cannot accept your
settings object. Call `export_environment()` explicitly for that integration.
This independent example proves that normal resolution leaves the environment
unchanged and export writes the dotenv value:

<!-- example-file: demo.py -->
```python
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

with TemporaryDirectory() as directory:
    path = Path(directory) / "deployment.env"
    path.write_text("DEMO_TIMEOUT=20\n", encoding="utf-8")
    before = dict(os.environ)
    resolved = MyRC.resolve(rc.ResolveOptions(env_files=(path,)), environment={})
    assert dict(os.environ) == before
    resolved.export_environment()
    assert os.environ["DEMO_TIMEOUT"] == "20"
    print("exported timeout: 20")
```

Run this in its own process with `python demo.py`. Export changes that process's
environment; it does not change the launching shell. It exports keys contributed
by dotenv files and the selected workspace key, rather than serializing every
Python default. A later direct constructor sees environment provenance and
cannot reconstruct the original file source. Prefer passing settings objects
within your own application.

## Generate a config package

From an empty working directory, run:

```shell
apprc scaffold config --package myapp --app-id myapp --target src --user-dotenv
```

The [scaffolder](References.md#public-namespaces) creates a package under
`src/myapp/config` containing the `AppRC` declaration, a config section, and a
config bundle. For a source-only smoke test, save this as `src/demo.py`:

```python
from myapp.config.app import MyRC
from myapp.config.bundle import MyappConfig

config = MyRC.resolve(environment={}).build(MyappConfig)
print(type(config).__name__)
```

Run `python src/demo.py`; it prints `MyappConfig`. Importing the bundle imports
its sections and registers them. Import a section directly when that is all the
application needs. Package initializers remain lightweight; the generated
package needs no catalog or lazy config facade. For a complete application
layout, examine the [example source files](EXAMPLES.md#choose-a-setup).

<br>

# Diagnose and migrate

## Troubleshoot configuration

Use the config CLI mounted in the [Typer guide](#add-configuration-commands-to-typer),
or an installed [example application](EXAMPLES.md#run-the-example-applications).
The commands below assume the `demo.py` from the Typer guide:

```shell
python demo.py paths config --json
python demo.py doctor --json
```
`paths` reports declared paths without creating them. Root `doctor` performs
read-only path and configuration diagnostics and exits nonzero for error-status
checks. It does not run application state factories or contact external services.

| Symptom | What to inspect or change |
| --- | --- |
| A saved edit has no effect | Compare [configuration layers](Explanations.md#configuration-layers); an explicit file or environment value may override the saved file. |
| A required field is missing | Read its [field definition](References.md#config-fields) and supply a value through an enabled source. Missing optional user files are allowed. |
| A workspace name is unknown | Check [workspace selector priority](References.md#workspace-selection); an invalid explicit selector does not fall back to the saved selection. |
| A workspace directory moved | Use `WorkspaceManager.repoint_workspace()` to record its new existing location. Setup does not recreate missing roots. |
| A path is disabled or unsafe | Check the `Paths` declaration and selected `Layout`; do not expect fallback to an old directory. |
| An edit is stale | [Inspect and plan again](#edit-or-remove-a-saved-override); another write changed the target file. |
| A direct settings constructor misses dotenv values | Use [`ResolvedConfig.build()`](Explanations.md#resolvedconfig), which receives the selected files' values. |

## Migrate existing applications

AppRC 0.30 is a breaking API, CLI, environment, and config-format cutover.
Update all callers and user-facing instructions before upgrading applications:

| Previous contract | Replacement |
| --- | --- |
| `Storage`, `storage=`, `ResolveOptions.storage`, `storage_required`, and `resolved.selection` | `Workspaces`, `workspaces=`, `ResolveOptions.workspace`, `workspace_required`, and `resolved.workspace`; application data roots are no longer workspace roots. |
| `apprc_dir`, `apprc_dir_env_key`, `legacy_app_ids`, or `*_APPRC_DIR` | Declare each used `Paths` category and choose `Layout.native()` or `Layout.single_root(root)`; use `<PREFIX>_LAYOUT` plus `<PREFIX>_ROOT` as one bootstrap pair. |
| `requires_storage=True` | `requires_workspace=True` when fields belong to a selected workspace. |
| `mount_config_cli`, `mount_appdata_cli`, `mount_config_group`, `appdata paths`, and `appdata clean` | `mount_app_cli` or `mount_app_groups`; use root `paths`, `doctor`, category groups, and exact-target `purge`. Supply providers for application-owned operations. |
| ConfigManager storage registry methods | Use `WorkspaceManager` methods such as `register_workspace()` and `archive_workspace()`. |
| `apprc.storage.env`, `apprc.storage.secret.env`, and old `storages` TOML records | New `apprc.workspace.env`, `apprc.workspace.secret.env`, and versioned `workspaces` schema. |
| Textual/Gradio storage controls | Provide `WorkspaceManager` separately from `ConfigManager`. |

Choose which independent components each application truly uses; `UserDotenv`
and registry-backed `Workspaces` both require `Paths(config=True)`. Use native
or single-root locations deliberately. Update command scripts and CI invocations
to the new grouped CLI and bootstrap controls.

**There is no automatic data migration.** AppRC does not search old directories,
move or rename user files, reinterpret the old registry, or delete old data.
Do not rename old `apprc.storage.*` files or expect an old registry to be
upgraded. Keep old files untouched. If users need their prior data, separately
review and export it using the application that owns its format, then explicitly
choose new paths and recreate registrations. Never place conversion in normal
startup or upgrade hooks. The current `config secrets` migration workflow is
only for declared secret assignments and does not convert layouts, filenames,
or registry schemas.

Other earlier API changes retain their existing guidance: resolve per run with
`MyRC.resolve(...)`, construct registered sections with `resolved.build(...)`,
use `MyRC.schema` instead of `MyRC.spec`, and explicitly inject custom
environment-backed bundle children. `Settings()` and `reload()` use live
process environment; use `reload_from()` with a resolved snapshot for managed
sources. `apprc-core` owns the Python source, while `apprc` adds terminal
dependencies. For package ownership changes, use a fresh virtual environment
or uninstall the old package before installing the new split distributions.
