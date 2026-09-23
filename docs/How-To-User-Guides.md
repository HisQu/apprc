# How-to user guides

[Documentation](README.md) · [Explanations](Explanations.md) · [References](References.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [Read typed settings](#read-typed-settings)
- [Declare an API key](#declare-an-api-key)
- [Load dotenv files](#load-dotenv-files)
- [Ship defaults with the application](#ship-defaults-with-the-application)
- [Find where a value came from](#find-where-a-value-came-from)
- [Save a user preference](#save-a-user-preference)
- [Use AppRC inside an importable client](#use-apprc-inside-an-importable-client)
- [Edit or remove a saved override](#edit-or-remove-a-saved-override)
- [Store data outside the source checkout](#store-data-outside-the-source-checkout)
- [Register and switch data directories](#register-and-switch-data-directories)
- [Move, reconnect, or archive storage](#move-reconnect-or-archive-storage)
- [Add configuration commands to Typer](#add-configuration-commands-to-typer)
- [Inspect and edit settings in the terminal](#inspect-and-edit-settings-in-the-terminal)
- [Pass several settings sections together](#pass-several-settings-sections-together)
- [Reload settings or use temporary overrides](#reload-settings-or-use-temporary-overrides)
- [Supply settings to environment-only code](#supply-settings-to-environment-only-code)
- [Generate a config package](#generate-a-config-package)
- [Troubleshoot configuration](#troubleshoot-configuration)
- [Migrate existing applications](#migrate-existing-applications)

Each guide is independent. Install AppRC using the [installation instructions](../README.md#install).
The Python examples run on Python 3.12 or newer. Examples using temporary
directories remove their files when they finish. CLI guides explicitly identify
the files they keep in the working directory.

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

<a id="set-up-persistence"></a>
## Save a user preference

Enable a [user dotenv](Explanations.md#user-dotenv-and-the-apprc-directory), then
use [`ConfigManager`](Explanations.md#configmanager) to initialize and edit it.
This example uses a temporary AppRC directory rather than changing your real
preferences. Run it as `demo.py`:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    MyRC = rc.AppRC(app_id="demo", user_dotenv=rc.UserDotenv(), apprc_dir=Path(directory))

    @MyRC.config("client", prefix="DEMO_")
    class ClientSettings(rc.Config):
        timeout: int = rc.field("DEMO_TIMEOUT", default=30)

    manager = MyRC.manage(environment={})
    manager.setup()
    plan = manager.plan_update("client.timeout", "20", scope="user")
    manager.apply_edit(plan)
    assert (Path(directory) / "apprc.user.env").is_file()
    assert manager.resolve().build(ClientSettings).timeout == 20
    print("saved timeout: 20")
```

In an application, omit `apprc_dir` to use the
[default AppRC directory](References.md#managed-files), or set `DEMO_APPRC_DIR`
to a persistent directory chosen by the user. Missing user dotenv files are
allowed when reading settings. `setup()` creates one explicitly and preserves
an existing file. The [user preferences example](EXAMPLES.md#persistent-user-preferences)
exposes this behavior through CLI commands.

If the declaration also enables storage, `setup()` expects a storage root.
Use `setup_user_dotenv()` to initialize only user overrides in that case.

<a id="edit-saved-values"></a>
## Use AppRC inside an importable client

A library can own its [`AppRC`](Explanations.md#apprc) declaration and load
settings when a client is constructed. Its caller then imports `Client` and does
not need to declare AppRC or call a setup function. This example uses a
[config section](Explanations.md#config-sections-and-fields), packaged defaults,
and a [user dotenv](Explanations.md#user-dotenv-and-the-apprc-directory).

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
    config_dir = Path(directory)
    os.environ["DEMO_APPRC_DIR"] = directory
    assert Client().timeout == 20

    (config_dir / "apprc.user.env").write_text("DEMO_TIMEOUT=15\n", encoding="utf-8")
    assert Client().timeout == 15

    os.environ["DEMO_TIMEOUT"] = "10"
    assert Client().timeout == 10
    print("packaged: 20; user: 15; process: 10")
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
    MyRC = rc.AppRC(app_id="demo", user_dotenv=rc.UserDotenv(), apprc_dir=Path(directory))

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
dotenv. Storage edits require an initialized storage. The
[combined setup](EXAMPLES.md#user-settings-and-storage) demonstrates both scopes.

> [!WARNING]
> Revision checks and same-process locking do not make edits transactional
> across processes. Another process can write between a revision check and
> replacement. Cross-process coordination remains planned work.

## Store data outside the source checkout

A [storage](Explanations.md#storage) supplies a directory path. Your application
uses that path when writing its own data. This complete `demo.py` uses a temporary
directory outside the checkout and deletes the demonstration data on exit:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    base = Path(directory)
    MyRC = rc.AppRC(app_id="demo", storage=rc.Storage(), apprc_dir=base / "config")
    manager = MyRC.manage(environment={})
    manager.setup(storage_root=base / "data", storage_name="work")
    resolved = MyRC.resolve(rc.ResolveOptions(storage="work", storage_required=True), environment={})
    assert resolved.selection is not None
    report = resolved.selection.root / "report.txt"
    report.write_text("Completed\n", encoding="utf-8")
    assert report.read_text(encoding="utf-8") == "Completed\n"
    print("report written to selected storage")
```

For persistent use, replace the temporary paths with a user-chosen data directory
and an [AppRC directory](References.md#managed-files). The storage directory
contains `apprc.storage.env` and the application's `report.txt`; the AppRC
directory contains the registry. The [storage-only example](EXAMPLES.md#named-storage-without-user-overrides)
provides a complete CLI with the same separation.

<a id="manage-storage"></a>
## Register and switch data directories

Register paths in the [storage registry](Explanations.md#storage-registry).
Choosing a saved default affects future resolutions; an explicit invocation
choice affects only that resolution. Run this `demo.py`:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    base = Path(directory)
    MyRC = rc.AppRC(app_id="demo", storage=rc.Storage(), apprc_dir=base / "config")
    manager = MyRC.manage(environment={})
    manager.setup(storage_root=base / "work", storage_name="work")
    manager.register_storage("personal", base / "personal")
    manager.select_storage("work")
    before = manager.resolve()
    personal = MyRC.resolve(rc.ResolveOptions(storage="personal"), environment={})
    assert before.selection is not None and before.selection.storage_name == "work"
    assert personal.selection is not None and personal.selection.storage_name == "personal"
    manager.select_storage("personal")
    assert before.selection.storage_name == "work"
    print("saved default changed; previous resolution still uses work")
```

An explicit invalid name fails instead of falling back to another directory.
An invocation can also select an initialized directory path without registering
it. The [selection reference](References.md#storage-selection) defines the
requirements and the relationship to environment variables.

## Move, reconnect, or archive storage

Use `move_storage()` when AppRC should move the data, and `repoint_storage()` when
the directory already moved. The following independent script exercises both,
then archives and restores the data inside one temporary directory:

<!-- example-file: demo.py -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    base = Path(directory)
    MyRC = rc.AppRC(app_id="demo", storage=rc.Storage(), apprc_dir=base / "config")
    manager = MyRC.manage(environment={})
    manager.setup(storage_root=base / "original", storage_name="work")
    (base / "original" / "report.txt").write_text("Completed\n", encoding="utf-8")
    manager.move_storage("work", base / "moved")
    (base / "moved").rename(base / "reconnected")
    manager.repoint_storage("work", base / "reconnected")
    archive = manager.archive_storage("work", base / "work.apprc.tar.xz")
    manager.restore_storage("copy", archive, base / "restored")
    assert (base / "restored" / "report.txt").read_text(encoding="utf-8") == "Completed\n"
    manager.remove_storage("copy")
    assert (base / "restored" / "report.txt").exists()
    print("restored and unregistered copy; its data remains")
```

The [operation reference](References.md#storage-operations) distinguishes
unregistering, deleting data, and forgetting an archive record. Moves require a
new or empty destination. Archive filenames must end in `.apprc.tar.xz`.
Archive creation retains the original directory.

> [!CAUTION]
> `remove_storage(name, delete_content=True)` deletes that directory's contents.
> Use the ordinary `remove_storage(name)` when only removing a registration.

<a id="integrate-a-terminal-application"></a>
## Add configuration commands to Typer

Install the `apprc` distribution, which includes terminal dependencies. Save
this complete application as `demo.py` in a new working directory:

<!-- example-file: demo.py -->
```python
import apprc as rc
import typer

MyRC = rc.AppRC(app_id="demo", user_dotenv=rc.UserDotenv())

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

app = typer.Typer()
rc.cli.mount_config_cli(app, MyRC)

@app.command()
def run(ctx: typer.Context) -> None:
    state = rc.cli.state_from(ctx, rc.cli.DefaultConfigCliState)
    assert state.resolved is not None
    settings = state.resolved.build(ClientSettings)
    typer.echo(settings.timeout)

if __name__ == "__main__":
    app()
```

These commands use a local demonstration directory. They are POSIX-shell syntax;
on PowerShell set `$env:DEMO_APPRC_DIR = "$PWD/demo-config"` instead of `export`.

```shell
export DEMO_APPRC_DIR="$PWD/demo-config"
python demo.py --help
python demo.py run
python demo.py config setup --yes
python demo.py config set client.timeout 20 --scope user
python demo.py run
python demo.py config doctor --json
```

With `DEMO_TIMEOUT` unset, the first run prints `30` and the second prints `20`.
The edit persists in `demo-config/apprc.user.env`. Root options such as
`--env-file deployment.env` go before the command. The
[command reference](References.md#terminal-commands) explains command availability.
The [custom-callback example](EXAMPLES.md#an-application-owned-cli-callback)
shows how to keep an application-owned Typer callback.

## Inspect and edit settings in the terminal

Use the installed [user preferences example](EXAMPLES.md#persistent-user-preferences)
to try the editor without first writing an application:

```shell
apprc-examples-lab user-dotenv
```

Inside the disposable shell, run:

```shell
apprc-user-dotenv config paths
apprc-user-dotenv config edit
```

If the user dotenv does not exist, use the editor's setup action. Select a
setting to read its explanation and compare its effective value with the layer
values. Save the override to the user dotenv, then run the application's `run`
command to observe the result. For an application with storage, select the
storage to inspect and choose the user or storage edit target explicitly.

The [config editor](Explanations.md#config-editor) displays defaults, explicit
files, and process-environment inputs alongside editable saved overrides.
It does not edit the parent shell or packaged defaults. An environment value
can therefore still win after a successful save. Browsing storage does not
change the [saved default](Explanations.md#storage-registry).

Opening the editor creates no files. Changes happen through explicit setup and
save actions. Exit the lab shell to remove its temporary settings and data.

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
by dotenv files and the selected storage key, rather than serializing every
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

## Troubleshoot configuration

Use the config CLI mounted in the [Typer guide](#add-configuration-commands-to-typer),
or an installed [example application](EXAMPLES.md#run-the-example-applications).
The commands below assume the `demo.py` from the Typer guide:

```shell
python demo.py config paths --json
python demo.py config doctor --json
```

`paths` reports where the application looks for managed files. `doctor` inspects
sources and fields without writing files and exits nonzero for readiness problems.
Neither needs all runtime settings to be valid.

| Symptom | What to inspect or change |
| --- | --- |
| A saved edit has no effect | Compare the [configuration layers](Explanations.md#configuration-layers); an explicit file or environment value may override the saved file. |
| A required field is missing | Read its [field definition](References.md#config-fields) and supply a value through an enabled source. Missing optional user files are allowed. |
| A storage name is unknown | Check the [registry and selector priority](References.md#storage-selection); an invalid explicit selector is not replaced with the default. |
| A registered directory was moved | [Reconnect the storage](#move-reconnect-or-archive-storage) to its existing path. Setup does not recreate a missing registered root. |
| An edit is stale | [Inspect and plan again](#edit-or-remove-a-saved-override); another write changed the target file. |
| A direct settings constructor misses dotenv values | Use [`ResolvedConfig.build()`](Explanations.md#resolvedconfig), which receives the selected files' values. |

## Migrate existing applications

This is a breaking API and packaging change. Managed filenames and registry
format remain unchanged; current storage data needs no conversion.

| Previous usage | Replacement |
| --- | --- |
| `MyRC.bootstrap(...)`, `ensure_bootstrapped()`, cached bootstrap result | `resolved = MyRC.resolve(rc.ResolveOptions(...))` per invocation |
| Bootstrap followed by `Settings()` | `resolved.build(Settings)` |
| `MyRC.kit` or `AppConfigKit` | `MyRC`, `MyRC.manage()`, or explicit interface functions |
| `MyRC.spec` | Read-only `MyRC.schema` |
| `MyRC.mount_cli(app)` | `rc.cli.mount_config_cli(app, MyRC)` |
| `kit.typer_app(...)` | `rc.cli.build_config_typer_app(MyRC, ...)` for a standalone config group |
| `Storage(required=True)` | `Storage()` and `ResolveOptions(storage_required=True)` or CLI `storage_required=True` |
| `UserDotenv(required=True)` | `UserDotenv()`; missing user files are allowed, required fields enforce value readiness |
| `state.env_bootstrap` | `state.resolved`; storage metadata is under `resolved.selection` |
| Raw write helpers under `rc.files` / `rc.storage` | Application-bound manager methods |
| `rc.cli.ConfigEditorApp`, `rc.cli.ConfigSetupApp` | `rc.tui.ConfigEditorApp`, `rc.tui.ConfigSetupApp` |
| Config catalog and package convenience exports | Direct section/bundle imports, then `MyRC.schema.owners` |
| `shell_bootstrap_selector` provenance | `shell_storage_selector` |
| `apprc[tui]` | Plain `apprc`; Textual is included |
| Small installation without terminal dependencies | `apprc-core` |

`Settings()` and `reload()` still use the live process environment. They no longer
recover file provenance from a previous global bootstrap. Use explicit construction
and `reload_from()` for managed sources. No hidden compatibility bootstrap runs.
Custom environment-backed bundle factories need explicit child injection.

For package ownership migration, use a fresh virtual environment or:

```shell
python -m pip uninstall apprc
python -m pip install apprc
```

The second command must install the new release once it is published. The root
source checkout now builds `apprc-core`; for a local terminal installation use
`python -m pip install -e . -e src/apprc_dev/packaging/terminal`.
Uninstalling the new wrapper later leaves `apprc-core` installed. A plain upgrade
from the old wheel is not the supported ownership-transfer procedure.

For old 0.19 filenames, retain the separate `config migrate --dry-run` workflow.
Do not rename data files as part of the API migration.
