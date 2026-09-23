# AppRC how-to guides

[Manual](README.md) · [Reference](References.md) · [Architecture](Explanations.md)

- [Integrate typed settings](#integrate-typed-settings)
- [Load dotenv inputs](#load-dotenv-inputs)
- [Compose a bundle](#compose-a-bundle)
- [Set up persistence](#set-up-persistence)
- [Edit saved values](#edit-saved-values)
- [Manage storage](#manage-storage)
- [Integrate a terminal application](#integrate-a-terminal-application)
- [Reload and export](#reload-and-export)
- [Generate a config package](#generate-a-config-package)
- [Troubleshoot configuration](#troubleshoot-configuration)
- [Migrate existing applications](#migrate-existing-applications)

## Integrate typed settings

Start with the [README example](../README.md#load-settings). The declaration needs
only `app_id`; `config_package` is optional. Import the sections you want before
calling `resolve()`. Registration after resolution does not change that snapshot.

Use `rc.Config` for fields backed by environment keys. Use `rc.ConfigBase` for
Python-only dataclass settings. A direct `Settings()` constructor reads the
current environment only. To include dotenv files and keep their provenance,
call `resolved.build(Settings)`.

Use `rc.field("DEMO_TOKEN", required=True, secret=True)` for a required secret.
The manager can inspect and repair incomplete settings without constructing a
runtime object. Avoid printing `resolved.values`; it contains raw inputs.

## Load dotenv inputs

```python
from pathlib import Path
import apprc as rc

options = rc.ResolveOptions(
    env_files=(Path("deployment.env"), Path("local.env")),
    env_file_overrides_os_environ=True,
)
resolved = MyRC.resolve(options, environment={})
settings = resolved.build(Settings)
```

Later explicit files win over earlier files. The option above lets them win over
the captured environment too. Without it, the environment wins. Interpolation
uses the captured mapping and assignments already parsed in that file.

For packaged defaults, set `config_package="myapp.config"` and include
`apprc.defaults.env` as package data. It is optional, including when the package
exists without that resource. An unimportable declared package is an error.
Archive-backed resources retain their package/resource identity in provenance.

`load_dotenv_layers=False` disables dotenv values for setting construction.
Explicit files are still read for structural storage and managed-directory
selection. See the [precedence reference](References.md#source-precedence).

## Compose a bundle

```python
from dataclasses import dataclass, field

@MyRC.bundle
@dataclass(kw_only=True)
class ApplicationConfig:
    app: Settings = field(default_factory=Settings)

resolved = MyRC.resolve()
config = resolved.build(ApplicationConfig)
```

AppRC replaces a registered section's ordinary class factory with construction
from the snapshot. It leaves Python-only factories and dataclass post-init hooks
intact. For a custom factory that creates an environment-backed child, inject the
child explicitly so the source is unambiguous:

```python
config = resolved.build(ApplicationConfig, app=resolved.build(Settings, retries=9))
```

Do not hide dotenv loading in a bundle factory or import side effect.

## Set up persistence

Declare the capabilities your application supports:

```python
MyRC = rc.AppRC(
    app_id="demo",
    user_dotenv=rc.UserDotenv(),
    storage=rc.Storage(),
)
manager = MyRC.manage(rc.ResolveOptions(apprc_dir=Path("./demo-config")))
manager.setup(storage_root=Path("./demo-data"), storage_name="local")
```

`setup()` initializes storage for a storage-capable app, and user overrides if
also declared. A user-only app calls `setup()` without a root.
`setup_user_dotenv()` initializes just the user layer, including in an app with
storage. Repeating setup at the same existing root preserves data. Setup does not
repoint a name or recreate a missing registered root.

`manager.paths`, `manager.inspect()`, and planning calls do not create files.
The `apprc_dir` option belongs to this manager or resolution and does not export
an environment variable.

## Edit saved values

```python
manager = MyRC.manage()
inspection = manager.inspect()
plan = manager.plan_update("app.retries", "6", scope="user")
preview = manager.preview_edit(plan)
manager.apply_edit(plan)
```

Field references may be a dotted registered path, an unambiguous field name, or
a full environment key. Values are validated before planning. The preview uses
runtime source precedence, so a higher-priority environment value can still win.

Plans preserve source text and carry a file revision. Duplicate assignments
produce warnings. The CLI and editor ask before applying duplicate cleanup when
interactive. Discarding a plan cancels it without writes.

If `manager.apply_edit(plan)` raises `rc.files.StaleEditError`, inspect again and
make a new plan. Do not blindly retry the old plan. To remove an override:

```python
plan = manager.plan_removal("app.retries", scope="user")
if plan is not None:
    manager.apply_edit(plan)
```

Use `scope="storage", storage="local"` to edit a particular storage without
changing the persisted default. `manager.writable_scopes()` lists initialized
scopes; `resolve_write_scope()` rejects an ambiguous automatic choice.
Explicit `plan_update(..., scope="user")` can create a missing user dotenv.

> [!WARNING]
> AppRC serializes its managed writes within one process. Revision checks reject
> stale dotenv plans, but another process can still write between the check and
> replacement. Cross-process transactions remain planned work before the GUI.

## Manage storage

```python
manager.register_storage("work", Path("./work-data"))
manager.select_storage("work")
resolved = MyRC.resolve(rc.ResolveOptions(storage="work", storage_required=True))
manager.rename_storage("work", "primary")
```

`select_storage()` changes the registry fallback for future resolutions. It does
not alter existing snapshots. `inspect(storage="primary")` only browses it.

| Operation | Data effect |
| --- | --- |
| `register_storage(name, root)` | Creates or registers the root and fixed dotenv |
| `select_storage(name)` | Changes the persisted default |
| `rename_storage(current_name, name)` | Changes the registry name |
| `repoint_storage(name, root)` | Points at an existing initialized directory; moves no files |
| `move_storage(name, destination)` | Moves data with preflight and rollback |
| `remove_storage(name)` | Unregisters; retains directory contents |
| `remove_storage(name, delete_content=True)` | Unregisters, then deletes the directory |
| `archive_storage(name, archive_path)` | Records an archive; retains the live directory |
| `restore_storage(name, archive_path, destination)` | Extracts and registers with rollback on registry failure |
| `remove_archive_record(name)` | Forgets the record; retains the archive file |

Directory deletion can fail after unregistering; inspect the registry and
remaining directory before retrying. These operations are not full filesystem
transactions.

`plan_migration()` / `apply_migration(plan)` handle released legacy layouts.
`plan_purge()` / `apply_purge(plan)` enumerate and remove fixed managed files and
registered internal storage. External storage data and unrelated files are kept.
Review these plans before applying them.

## Integrate a terminal application

Install `apprc` and use [the small mounting example](../README.md#add-terminal-commands).
Its callback adds `--env-file`, `--env-file-overrides-os-environ`,
`--skip-dotenv-layers`, `--storage` when supported, and `--log-level`.
Options precede the subcommand:

```shell
demo --env-file deployment.env config doctor
demo config setup --yes --storage-root ./data
demo config set app.retries 6 --scope user
demo config edit
demo config storage list
```

Help, setup, paths, doctor, and editing work before runtime settings are valid.
`config show` and application commands can use `state.resolved.build(...)`.
Doctor exits nonzero for readiness problems, including invalid required fields.

If your app already has a Typer callback, construct `rc.cli.CliRuntime(MyRC, ...)`
and call its `prepare(ctx, options)` from that callback. A state factory receives
`CliRuntimeContext`, whose `resolved` member is the snapshot. Keep app-only CLI
options in your own state dataclass. See the executable
[CLI runtime example](../examples/example_apps/src/cli_runtime/cli.py).
Use `CliRuntimePolicy` to declare runtime-independent commands.

The editor uses the same sources and manager as runtime. Browsing storage does
not select it for future runs. Relocation during setup stays local to that editor
session. Public Textual classes are `rc.tui.ConfigEditorApp` and
`rc.tui.ConfigSetupApp`.

## Reload and export

```python
settings.reload_from(MyRC.resolve())
```

A reload validates a candidate before changing the object. Removed source values
return to Python defaults. Constructor overrides, assignments, and scoped
overrides remain authoritative unless `override_python_values=True` is passed.
A failed reload leaves the previous values and provenance intact.

For a dependency that only reads environment variables:

```python
resolved = MyRC.resolve()
resolved.export_environment()
```

Export is a deliberate process-wide overlay. It exports effective keys supplied
by dotenv layers and the selected storage key, including environment winners
for those keys. It does not remove unrelated environment values, establish a
restorable baseline, or transfer file provenance to later direct constructors.
Prefer passing constructed settings to your own code.

## Generate a config package

```shell
apprc scaffold config --package myapp --app-id myapp --target src --user-dotenv
```

The generated layout contains `config/app.py`, `config/sections/app.py`, an
optional-use `config/bundle.py`, and lightweight package initializers. It has no
catalog, lazy facade, or facade stub. Import directly:

```python
from myapp.config.app import MyRC
from myapp.config.bundle import MyappConfig

config = MyRC.resolve().build(MyappConfig)
```

Importing the bundle registers its sections. Import a leaf section when you only
need that section. Obtain the registered inventory through `MyRC.schema.owners`.
Module names are an application convention; doctor does not enforce a layout.

## Troubleshoot configuration

Run `demo config paths --json` to inspect the selected directory and storage.
Run `demo config doctor --json` for source and required-field readiness without
writing files. A missing user dotenv is an empty optional layer.

If a named storage was moved manually, use `config storage repoint NAME ROOT`.
Use `config storage move NAME DESTINATION` only when AppRC should move the files.
An invalid explicit selector is not silently replaced by the registry default.

If a saved value appears ineffective, inspect the explicit files and captured
environment. They may outrank the saved layer. `manager.inspect().fields` exposes
the effective value and origin; `display_value` redacts declared secrets.

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
