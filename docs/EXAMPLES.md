# Examples

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Development](Development.md)

- [Choose and run an example](#choose-and-run-an-example)
  - [Choose a setup](#choose-a-setup)
  - [Run the example applications](#run-the-example-applications)
- [Settings examples](#settings-examples)
  - [Settings without managed files](#settings-without-managed-files)
  - [Persistent user preferences](#persistent-user-preferences)
  - [Importable client with saved preferences](#importable-client-with-saved-preferences)
- [Independent paths and workspaces](#independent-paths-and-workspaces)
  - [Inspect installation independently](#inspect-installation-independently)
  - [Cache-only application](#cache-only-application)
  - [Single-root application paths](#single-root-application-paths)
  - [User preferences and workspaces](#user-preferences-and-workspaces)
- [Repository-owned installation composition](#repository-owned-installation-composition)
  - [Default lifecycle](#default-lifecycle)
  - [Customized ordering](#customized-ordering)
- [Other application patterns](#other-application-patterns)
  - [Explicit dotenv precedence](#explicit-dotenv-precedence)
  - [Parent-owned dependency settings](#parent-owned-dependency-settings)
  - [An application-owned CLI callback](#an-application-owned-cli-callback)
  - [Several sections and temporary overrides](#several-sections-and-temporary-overrides)

<br>

# Choose and run an example

## Choose a setup

Choose only the resources your application uses. `Paths` independently enables
config, appdata, cache, and state; `UserDotenv` and `Workspaces` are separate
features that require config only when they use managed config files or a
registry.

| Setup | Declared paths | Additional feature | Choose it when |
| --- | --- | --- | --- |
| [Settings without managed files](#settings-without-managed-files) | None | None | Process environment and defaults supply settings. |
| [Persistent user preferences](#persistent-user-preferences) | Config | `UserDotenv()` | Users save preferences, but the application needs no other managed resource. |
| [Importable client with saved preferences](#importable-client-with-saved-preferences) | Config | User dotenv and packaged defaults | Callers construct a library client without declaring AppRC. |
| [Cache-only application](#cache-only-application) | Cache | None | The application needs disposable cache and nothing else. |
| [Inspect installation independently](#inspect-installation-independently) | None or any chosen subset | Read-only installation manager | A management command must inspect saved authority without business settings or enabling appdata. |
| [Single-root application paths](#single-root-application-paths) | Any chosen subset | Explicit layout | The application wants enabled categories colocated beneath a caller-owned root. |
| [User preferences and workspaces](#user-preferences-and-workspaces) | Config | User dotenv and registry-backed `Workspaces()` | Users share preferences and select named working directories. |
| [Parent-owned dependency settings](#parent-owned-dependency-settings) | Parent's chosen paths | Imported config binding | The host owns dependency field names and values. |

## Run the example applications

From an AppRC checkout, install the core, terminal distribution, and examples:

```shell
python -m pip install -e . -e src/apprc_dev/packaging/terminal -e examples/example_apps
```

`apprc-examples-lab NAME` opens an isolated shell for one example. The lab sets
its environment and creates its own temporary root. Example commands use current
`paths`, `doctor`, category, workspace, and root `purge` commands; no old AppRC
storage or `appdata clean` command is used. Keep demonstration data inside the
lab root because paths explicitly chosen elsewhere remain after the lab exits.

The [example package README](../examples/example_apps/README.md) describes the
lab and smoke runner. Complete source code remains in `examples`; the guides
below explain the decisions each setup demonstrates.

<br>

# Settings examples

## Settings without managed files

A script can use settings without declaring a filesystem category:

```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

first = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
second = MyRC.resolve(environment={"DEMO_TIMEOUT": "20"})
assert first.build(ClientSettings).timeout == 10
assert second.build(ClientSettings).timeout == 20
assert MyRC.resolve(environment={}).build(ClientSettings).timeout == 30
```

Each `ResolvedConfig` captures independent inputs. This example creates no files.
The runnable [process_env declaration](../examples/example_apps/src/process_env/config/app.py)
shows the same configuration approach in a CLI.

## Persistent user preferences

The [user_dotenv declaration](../examples/example_apps/src/user_dotenv/config/app.py)
enables `Paths(config=True)` and `UserDotenv()`. The lab sequence initializes
preferences, saves a value, then launches the application:

```shell
apprc-examples-lab user-dotenv
```

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-user-dotenv paths config
apprc-user-dotenv config init
apprc-user-dotenv config setup --yes
apprc-user-dotenv config set app.profile personal --scope user
apprc-user-dotenv run
apprc-user-dotenv config edit
```

The edit is saved in `apprc.user.env` beneath the config category root. The
[Python preference guide](How-To-User-Guides.md#save-a-user-preference) shows the
same operation through `ConfigManager`.

`apprc-user-dotenv launcher` opens the same editor inside a single Textual event
loop. Its **Print active configuration** action runs the actual example command
in the foreground and resumes the launcher afterward. Captured selectors and
the same Python environment's absolute command are retained; the
[example CLI source](../examples/example_apps/src/user_dotenv/cli.py) owns this spec.

## Importable client with saved preferences

The [`library_client` package](../examples/example_apps/src/library_client/README.md)
owns its declaration and client. Its caller imports the public client and need
not call AppRC directly:

```python
from library_client import LibraryClient

client = LibraryClient()
print(client.request_timeout)
```

The client resolves settings when constructed and does not initialize config
files. A separate user setup command initializes the configured user dotenv.
This keeps library construction read-only while making preferences opt-in.

<br>

# Independent paths and workspaces

## Inspect installation independently

Inspection does not require a resource declaration or resolved business settings:

```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")
inspection = MyRC.installation().inspect()
print(inspection.status)
print(inspection.directory)
for diagnostic in inspection.diagnostics:
    print(diagnostic.code, diagnostic.message)
```

This reads only the fixed native address. It does not initialize appdata or
another resource, execute uv, or create an installation record. `"missing"` is
normal for an unmanaged editable pip installation; an invalid record remains
inspectable rather than selecting a different data location.

The existing cache-only CLI exposes the same management route:

```shell
apprc-examples-lab cache-only
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-cache-only installation show --json
apprc-cache-only installation doctor --json
```

Declaring cache does not enable config/appdata/state. Managed installation
support, when deliberately installed, is independent of that declaration and
is not a cache cleanup target. See the
[recovery guide](How-To-User-Guides.md#install-and-recover-managed-applications)
and [record reference](References.md#installationmanager).

## Cache-only application

The maintained `cache_only` example declares only cache and has no schema,
config, registry, or maintenance provider:

```python
import apprc as rc

MyRC = rc.AppRC(app_id="cache-demo", paths=rc.Paths(cache=True))
cache_dir = MyRC.ensure_path("cache")
print(cache_dir)
```

Run its actual installed command in a disposable lab:

```shell
apprc-examples-lab cache-only
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-cache-only --help
apprc-cache-only paths --json
apprc-cache-only cache init
apprc-cache-only paths cache --json
```

`paths --json` reports the declared locations and existence without creating
any directory. `cache init` initializes only cache and its owner marker; config,
appdata, state, logs, and workspace locations remain disabled. The grouped help
contains paths, doctor, installation, cache info/init, and purge, but no config,
workspace, appdata, or state groups. Cache data initialization belongs at the application's
actual write boundary, not matcher/service construction.

## Single-root application paths

This complete example chooses only appdata and cache beneath an explicit root:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import apprc as rc

with TemporaryDirectory() as directory:
    MyRC = rc.AppRC(
        app_id="demo",
        paths=rc.Paths(appdata=True, cache=True),
        layout=rc.Layout.single_root(Path(directory)),
    )
    before = MyRC.paths()
    assert before.config_dir is None
    assert before.appdata_dir == Path(directory) / "appdata"
    assert before.cache_dir == Path(directory) / "cache"
    assert not before.cache_dir.exists()
    cache_dir = MyRC.ensure_path("cache")
    assert cache_dir.is_dir()
    assert not before.appdata_dir.exists()
```

Inspection is read-only; ensuring cache creates only that category and its
ownership marker. If an existing nonempty unowned path is intentional,
`ensure_path("appdata", adopt=True)` is explicit adoption, not migration: it
claims the directory but moves or deletes nothing. A mismatched owner marker,
symlink, junction, or overlapping managed root refuses mutation.

## User preferences and workspaces

`Workspaces()` provides named roots and an optional config overlay; selecting one
does not change the resolved application paths. The example declaration is:

```python
import apprc as rc

MyRC = rc.AppRC(
    app_id="demo",
    paths=rc.Paths(config=True),
    user_dotenv=rc.UserDotenv(),
    workspaces=rc.Workspaces(selector_env_key="DEMO_WORKSPACE"),
)
```

Registry files and user preferences share the enabled config root. Each
workspace's `apprc.workspace.env` and `apprc.workspace.secret.env` live in its
workspace root. `WorkspaceManager` registers, selects, renames, repoints, moves,
archives, and restores workspace roots. Unregistering retains payloads. The
[workspace guide](How-To-User-Guides.md#select-a-workspace) describes direct
registry-free selection as well.

A `Workspaces(registry=False)` declaration accepts direct directory paths
without config or a registry; it does not persist named registrations. For
layout bootstrap, `<PREFIX>_LAYOUT` and `<PREFIX>_ROOT` are interpreted as one
pair from one highest-priority raw input layer. Root alone means single-root;
`native` plus root in that layer is invalid. The [layout reference](References.md#layout-bootstrap)
describes priority, including explicit-file precedence.

<br>

# Repository-owned installation composition

These maintained examples are ordinary composition functions for a repository
payload, not standalone console installers. Include the chosen modules/resources
in a `PayloadTree` and generate runnable entries through
[`apprc.distribution`](References.md#distribution-generation). They need no
Buildben inheritance or global hook registry.

## Default lifecycle

The [default install function](../examples/example_apps/src/distribution_default/install.py)
accepts the captured plan and explicit `SourceSelection`, acquires it in private
staging, then calls `install_prepared_application(...)` with the target probe,
support bytes and Python requirement. The shared transaction owns the safety
boundary: it validates source/backend, probes the actual installed target,
publishes support and commits observed authority.

The [default removal function](../examples/example_apps/src/distribution_default/uninstall.py)
uses `prepare_uninstall(...)`, rejects an unsafe preview, starts the independent
handoff, waits for readiness and signals exit immediately before `SystemExit`.
The calling application must obtain consent first. This function removes the
program only; it does not interpret retention as permission to delete data.

## Customized ordering

The [custom install function](../examples/example_apps/src/distribution_custom/install.py)
parses transport with `parse_source_arguments(...)` before application options
and plans with the returned `selection.source`. It calls
`selection.prepare(...)`, runs the repository's own project-setup function,
then passes that exact `PreparedSource` to `install_prepared_application(...)`.
The author controls this sequence without editing shared runtime or copying
its transaction implementation.

The [custom removal function](../examples/example_apps/src/distribution_custom/uninstall.py)
supplies project cleanup to the shared handoff. Cleanup receives an explicit
pending `OperationContext`; application maintenance can use
`MyRC.maintain(context=context, handlers=...)` instead of fabricating a normal
runtime context or ignoring an incomplete record. Cleanup must finish while
required program/provider code remains available.

Keep ownership inventories, process quiescence and consent explicit when
adapting these examples. Closing a screen is not process exit, and successful
program removal is not successful complete data/authority removal. See the
[recovery guide](How-To-User-Guides.md#install-and-recover-managed-applications)
for their user-facing distinction.

<br>

# Other application patterns

## Explicit dotenv precedence

The [precedence application](../examples/example_apps/src/explicit_env_precedence/cli.py)
demonstrates explicit files and process values. By default process environment
wins; `env_file_overrides_os_environ=True` makes explicit dotenv values win.
Each explicit file remains a distinct layer for the layout bootstrap pair.
See the [source precedence reference](References.md#source-precedence).

## Parent-owned dependency settings

The complete [dependency_config_import.py](../examples/dependency_config_import.py)
imports a dependency section under a host-owned namespace. The host controls its
fields, defaults, and secret metadata while importing values from its own
resolved snapshot. Dependency environment variables, files, workspace selector,
registry, and layout bootstrap keys are excluded. Dependency packaged defaults
remain opt-in. This example does not require model calls or external services.

## An application-owned CLI callback

The [cli_runtime application](../examples/example_apps/src/cli_runtime/cli.py)
owns its root callback and runtime state. It uses `mount_app_groups(app)` and
`CliRuntime.prepare()` rather than the high-level callback-owning
`mount_app_cli`. Maintenance commands bypass business-state construction while
capturing the same paths/layout snapshot.

## Several sections and temporary overrides

The complete [section_bundle.py](../examples/section_bundle.py) defines client
and output sections, registers their dataclass bundle, and builds both from one
`ResolvedConfig`. The example also demonstrates temporary settings overrides and
reloads; these configuration features are independent of the application's path
selection. See the [bundle guide](How-To-User-Guides.md#pass-several-settings-sections-together).
