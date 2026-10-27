# Explanations

[Documentation](README.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [Define and resolve settings](#define-and-resolve-settings)
  - [AppRC](#apprc)
  - [Config sections and fields](#config-sections-and-fields)
  - [ResolvedConfig](#resolvedconfig)
  - [Configuration layers](#configuration-layers)
  - [Provenance](#provenance)
- [Save settings and application data](#save-settings-and-application-data)
  - [User dotenv](#user-dotenv)
  - [Secret companions](#secret-companions)
  - [Application paths](#application-paths)
  - [Workspaces](#workspaces)
  - [Layouts](#layouts)
  - [Maintenance](#maintenance)
- [Inspect and edit configuration](#inspect-and-edit-configuration)
  - [ConfigManager](#configmanager)
  - [Application CLI](#application-cli)
  - [Config editor](#config-editor)
  - [Gradio editor](#gradio-editor)
- [Compose and ship applications](#compose-and-ship-applications)
  - [Config bundles](#config-bundles)
  - [Imported dependency settings](#imported-dependency-settings)
  - [Copies, overrides, and reloads](#copies-overrides-and-reloads)
  - [Installed packages and installer builds](#installed-packages-and-installer-builds)

This page explains typed settings, independent application paths, optional
workspaces, configuration tools, and application-owned maintenance operations.
A small application can use settings alone or declare one path such as cache.


<br>

# Define and resolve settings

<a id="declaration-resolution-and-management"></a>
## AppRC

`rc.AppRC` is the declaration of one application's configuration. Create it
once, usually in the application's `config/app.py`, and import that object
where the application declares or loads settings.

The declaration records the application's identity. For example,
`rc.AppRC(app_id="demo")` identifies settings as belonging to `demo`. If the
application later enables saved settings, AppRC uses that identity to derive
the directory and environment-variable names.

An application can also set [`setup_next_step`](References.md#declarations) to
show an app-supplied next-step message after a user finishes explicit CLI
setup.

Register a [config section](#config-sections-and-fields) on this object with
`@MyRC.config(...)`. Registration tells AppRC which fields belong to the
application. It makes the same field definitions available to configuration
loading, the config editor, and diagnostic commands. Import the modules that
declare the sections before resolving settings.

An `AppRC` declaration does not hold the current value of every setting.
Its two main operations have different jobs:

| Operation | What it creates | What you use it for |
| --- | --- | --- |
| [`MyRC.manage()`](References.md#configmanager) | A [`ConfigManager`](#configmanager) bound to this declaration | [Initialize or edit saved settings](How-To-User-Guides.md#save-a-user-preference). |

The [basic settings example](EXAMPLES.md#settings-without-managed-files) uses
only `resolve()`. The
[user preferences example](EXAMPLES.md#persistent-user-preferences) adds config files.

## Config sections and fields

A config section is a Python class containing related settings. An API client
might have a section for its endpoint and timeout; a report writer might have
another section for its output format. An instance of the class holds the
values used by that part of the application.

Use `rc.Config` for a section that accepts values from environment keys:

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

settings = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"}).build(ClientSettings)
assert settings.timeout == 10
```

The config field connects the Python attribute `timeout` to `DEMO_TIMEOUT`.
The annotation `int` tells AppRC to convert the input string to an integer.
`default=30` supplies a fallback when no configuration layer provides a value.
Without a default, the field is required unless explicitly declared otherwise.
The [field reference](References.md#config-fields) specifies the accepted options.

Field documentation stays next to the field. `title` is its readable name;
`explanation_short` describes it in a table; `explanation_long` provides the
editor's longer explanation. The CLI and editor read these definitions, so an
application does not need to maintain separate lists of settings for each tool.

`choices` restricts accepted string values. `editable=False` prevents normal
editor changes to a field controlled by the application. Set
`restart_required=True` when a saved value only takes effect after restarting
the application. The Textual and Gradio editors mark the setting and repeat
the restart instruction after saving; AppRC does not restart the application.
`secret=True` hides a value in AppRC's display output. A secret value still
exists in memory and may be stored as plaintext in a dotenv file; this flag
does not provide encryption or a credential store. The
[API-key guide](How-To-User-Guides.md#declare-an-api-key) shows a required
secret field.

Use `rc.ConfigBase` for Python-only sections that do not read environment keys.
Both kinds can be fields of a [config bundle](#config-bundles). A section is an
application grouping; it is not a separate dotenv file. The same file can supply
values for several sections.

## ResolvedConfig

`ResolvedConfig` captures setting sources, the selected workspace, and `AppPaths`
for one run. `MyRC.resolve()` reads configuration and bootstrap inputs without
creating directories or changing `os.environ`. The same resolved snapshot keeps
its original layout and path provenance even if settings are refreshed.

`resolved.build(ClientSettings)` uses those values to construct a settings
object. This is where AppRC converts field values and checks required fields.
For example, the string `"10"` becomes an integer timeout; `"ten"` fails conversion.
Application functions can then receive `ClientSettings` and access `settings.timeout`.
They do not need to read environment variables themselves.

An importable client can keep the `AppRC` declaration inside its package and
call `resolve().build(ClientSettings)` when the client is constructed. The
caller then writes `Client()` without importing AppRC. The library still accepts
an already built section when several clients must use one snapshot. The
[importable-client guide](How-To-User-Guides.md#use-apprc-inside-an-importable-client)
shows both sides of this boundary.

There are two separate objects because reading sources and constructing settings
are different tasks. The same `ResolvedConfig` can build several registered
sections from the same inputs. A missing required field in one section does not
prevent the [config editor](#config-editor) from inspecting and repairing it.

<a id="why-explicit-snapshots"></a>
Resolving again creates another `ResolvedConfig`. If a file changes between
the two calls, the second result can contain new values while the first keeps
the values it read. Selecting another workspace also leaves the captured
`AppPaths` unchanged. This permits separate tests or application jobs to use
different settings and working directories in the same Python process.

Passing `environment={}` excludes process environment values. Passing another
mapping supplies controlled inputs, as in the [basic example](EXAMPLES.md#settings-without-managed-files).
Omitting the argument captures the current process environment. The
[resolution reference](References.md#resolution) lists the available options.

Calling a section's constructor directly, such as `ClientSettings()`, reads the
live process environment. It does not read the files chosen by `resolve()`.
Use `resolved.build(...)` when the application uses AppRC's configuration layers.

## Configuration layers

A configuration layer is one source of setting values. AppRC reads layers in
a defined order. A later value for the same environment key replaces an earlier
value; keys absent from the later layer retain their earlier values.

The usual priority, from lowest to highest, is:

| Source | Why it exists |
| --- | --- |
| Python field default | A fallback written beside the field's type and documentation. |
| Packaged `apprc.defaults.env` | Defaults shipped as data inside the application package. |
| [User dotenv](#user-dotenv) | Preferences saved for this user. |
| User [secret companion](#secret-companions) | Secret fields saved for this user; takes priority over the ordinary user dotenv. |
| Selected workspace dotenv | Overrides for the selected workspace. |
| Workspace secret companion | Declared secret fields saved for the selected workspace. |
| Explicit dotenv files | Extra inputs supplied for this invocation. |
| Process environment | Values inherited by the process, often exported by a shell or deployment system. |

For example, a timeout of `30` in Python, `20` in the user dotenv, and `10` in
the process environment produces `settings.timeout == 10`. Editing the user
dotenv to `15` still produces `10` while that environment value is present.
The [precedence example](EXAMPLES.md#explicit-dotenv-precedence) demonstrates this
with distinct values so the winning source is visible.

An application does not need all these layers. Packaged defaults require a
`config_package`; user and workspace files require their respective declarations.
The [dotenv guide](How-To-User-Guides.md#load-dotenv-files) shows how to supply an
explicit file without enabling saved preferences or a workspace.

Constructor arguments override the resolved value for the constructed object.
The [source precedence reference](References.md#source-precedence) also describes
the option that puts explicit files above the process environment, and the rules
for interpolation and missing files.

## Provenance

Provenance is the record of where a field's current value came from. It answers
"Why is the timeout 10?" by identifying the process environment as the source,
instead of making the user search every dotenv file.

`settings.provenance_of("timeout")` returns that record. File-based values retain
their source path; packaged defaults retain their package and resource name.
Python defaults, constructor arguments, assignments, and scoped overrides have
their own origin records. The [provenance guide](How-To-User-Guides.md#find-where-a-value-came-from)
shows how to inspect a record, and [References](References.md#provenance-and-lifecycle)
defines the fields it contains.

The [config editor](#config-editor) also displays the contributing layers. A user
can see that an override was saved successfully while a higher-priority environment
value still wins. Provenance explains the effective value; the layer display
helps the user compare the alternatives.

<br>

# Save settings and application data

<a id="capabilities-and-runtime-requirements"></a>
## User dotenv

The user dotenv is `apprc.user.env`, a file of saved preferences for one
application user. Declare `user_dotenv=rc.UserDotenv()` to enable it, and also
enable the config component with `paths=rc.Paths(config=True)`. The requirement
is explicit: user preferences never turn on a path category.

The file is derived from `AppPaths.config_dir`. `MyRC.paths()` inspects the
captured location without creating it; `MyRC.ensure_path("config")` initializes
that category and records `.apprc-owner.json` before a managed write. See the
[path reference](References.md#application-paths) for native and single-root
placement. Missing optional files contribute no values when resolving.

## Secret companions

A secret companion is a private dotenv file beside a managed layer. For
`secret=True`, `ConfigManager` writes user values to `apprc.user.secret.env` and
workspace values to `apprc.workspace.secret.env`. Each companion is read after
its ordinary dotenv, so secrets override ordinary assignments in that same
layer. The [secret guide](How-To-User-Guides.md#save-and-repair-secret-settings)
covers deliberate secret repair and movement within the current secret workflow.

AppRC does not encrypt these files. On Linux and macOS, the parent directory
must be mode `0700` and the file `0600`; on Windows AppRC checks access by
ordinary other users. `config secrets repair` changes permissions only after
the user requests repair. A workspace archive omits its secret companion and
refuses to include declared secret assignments left in an ordinary workspace
dotenv. A separate deliberate backup of secrets remains the user's
responsibility.

## Application paths

`Paths` is an opt-in declaration, not a record of existing directories:

```python
import apprc as rc

MyRC = rc.AppRC(
    app_id="demo",
    paths=rc.Paths(config=True, appdata=True, cache=True, state=True),
    layout=rc.Layout.native(),
    user_dotenv=rc.UserDotenv(),
)

locations = MyRC.paths()
config_dir = MyRC.ensure_path("config")
```

The four booleans enable config, appdata, cache, and state independently. Logs
are subordinate to state, not a fifth enabled category. With all booleans false,
path resolution still returns an `AppPaths` record whose locations are `None`.
`AppPaths.require(kind)` raises `ValueError` for a disabled location.

`AppPaths` captures the chosen layout, source, and absolute component locations
for one invocation. `paths()` is read-only: it neither creates directories nor
repairs ownership. `ensure_path(kind)` creates only the requested enabled root,
privately, and writes a `.apprc-owner.json` marker containing
`schema_version: 1`, `app_id`, and category. `ensure_path("state")` does not
create logs; `ensure_path("logs")` initializes only the log location, with state
ownership initialized first when logs are nested within state.

Creation refuses symlinks/junctions, overlapping category roots, mismatched
markers, and nonempty unowned directories. `adopt=True` on `ensure_path` is the
explicit choice to claim a nonempty unowned root; it does not move or delete its
contents. Config setup uses the same ownership checks, and
`config init --adopt` provides explicit config adoption. Ordinary settings edits
do not adopt unrelated directories. Read-only path inspection diagnoses unsafe
locations without creating markers or changing files.

No code scans old locations as fallback. A path declaration alone does not
enable `UserDotenv`, workspaces, or a provider operation. Ordinary application
code can obtain an enabled directory and use its own database/files; maintenance
providers are needed only for app-specific backup, restore, pruning, reset, or
purge operations.

## Workspaces

`Workspaces(selector_env_key=None, registry=True)` declares optional selection
of an application's working directory. A registered workspace has a name, a
root, and a config overlay; its selection affects workspace settings and
`ResolvedConfig.workspace`, never `AppPaths`. Registry-backed workspaces require
`Paths(config=True)`, because the registry is `apprc.toml` in the config root.
The new TOML has `schema_version = 1`, `selected_workspace`,
`[workspaces.NAME] root = ...`, and `[archived_workspaces.NAME] archive/source_root`.

`MyRC.workspaces()` returns a `WorkspaceManager` for explicit list, register,
select, rename, repoint, move, remove, archive, and restore operations.
`initialize_workspace(root)` prepares a direct workspace root by creating
`apprc.workspace.env`; it writes no config or registry file, and creates no
secret companion until needed. Removing a registry entry does not delete its
payload. New registered roots may not overlap AppRC-managed category roots. A
workspace dotenv is `apprc.workspace.env`; secret assignments use
`apprc.workspace.secret.env`. Config scope `workspace` writes to the currently
selected workspace.

`Workspaces(registry=False)` permits a direct directory selector without config,
registry reads, or registration prompts. Relative direct selectors resolve
against invocation current working directory. Call
`WorkspaceManager.initialize_workspace(root)` before selecting a new direct
root; `workspace init PATH` and `workspace info PATH` are the corresponding CLI
commands. Named selectors fail with
`ValueError("Named workspaces require a registry.")`; direct mode does not offer
registration persistence.

The selector defaults to `<PREFIX>_WORKSPACE`. Invocation `ResolveOptions.workspace`
or `--workspace` wins over the selector environment/file values and saved
registry default. Workspace selection is independent of the layout bootstrap
pair. See [selection precedence](References.md#workspace-selection) and the
[workspace guide](How-To-User-Guides.md#select-a-workspace).

## Layouts

`Layout.native()` uses platformdirs user locations for each enabled category.
`Layout.single_root(root)` resolves `root` once against invocation current
working directory and maps enabled categories to `root/config`, `root/appdata`,
`root/cache`, and `root/state`, with logs under `root/state/logs`. Disabled
components remain `None` in either layout. Native category suffix rules are
independent, so enabling another category does not relocate existing ones.

Layout bootstrap controls are `<PREFIX>_LAYOUT` and `<PREFIX>_ROOT`. The
normalized application ID supplies the prefix unless `bootstrap_env_prefix` is
set. Invocation `Layout` has highest priority. Otherwise AppRC selects one whole
raw layer containing either nonblank control and interprets only that layer's
pair: root alone means single-root; `native` with root in the same pair is an
error; higher-layer `native` ignores lower-layer root. Process environment
normally outranks explicit dotenv files in reverse argument order; setting
`env_file_overrides_os_environ=True` reverses that layer precedence. A managed
dotenv cannot relocate itself. `AppPaths.source` records invocation,
environment, declaration, or default selection. See the complete
[bootstrap reference](References.md#layout-bootstrap).

## Maintenance

`AppRC.maintain(..., handlers=MaintenanceHandlers(...))` supplies explicit
category handlers. Enabled paths provide basic `info`; semantic backup,
restore, prune, clear, reset, and purge operations appear only when their
operation is supplied. Providers for disabled categories are declaration
errors. `AppDataOperations`, `CacheOperations`, and `StateOperations` use named
fields rather than arbitrary operation dispatch.

Purge planning lists exact managed files and empty directories, tracks a
revision, and refuses unknown or unowned contents. Apply rechecks markers,
boundaries, links, and revisions immediately before dispatch; provider
operations repeat freshness and lease checks under their coordination lock.
It never grants permission to delete a single-root parent or a workspace.
Multiple roots are not an atomic transaction; partial and skipped results are
reported. Missing roots produce empty plans without creating markers. The
[maintenance reference](References.md#maintenance) documents result shapes.

<br>

# Inspect and edit configuration

<a id="interfaces-and-shared-operations"></a>
## ConfigManager

`ConfigManager`, returned by `MyRC.manage()`, performs operations on settings
files and current secret workflows. Creating it does not write. `inspect()`
reports field values and individual problems; `setup(*, adopt=False)`
initializes only enabled user configuration. Workspace registration is owned by
`WorkspaceManager`, not config setup.

An edit has an explicit review step. `plan_update()` validates the value and
records the target revision; `preview_edit()` shows effective settings;
`apply_edit()` writes only if the file still matches that revision. Editing a
file does not change an earlier resolved snapshot. Atomic replacements and
cross-process locks protect managed writes, but multiple filesystem roots are
not one transaction. See [management reference](References.md#configmanager).
## Application CLI

`rc.cli.mount_app_cli(app, MyRC, ...)` mounts fixed groups for available
capabilities and returns a dictionary of mounted category subgroups. It owns the
root callback and rejects replacement of an existing callback. Applications
that own a callback use `CliRuntime.prepare()` and its `mount_app_groups()`
method. Both routes use one captured bootstrap/path snapshot. Maintenance
commands skip business-state construction while retaining that snapshot.

`paths [CATEGORY]` and `doctor` are always mounted. The `config`, `workspace`,
`appdata`, `cache`, and `state` groups appear only when their required
declarations exist. The root `purge` command handles AppRC-owned exact targets;
category commands expose only supported provider operations. The
[command reference](References.md#terminal-commands) gives availability,
options, JSON, and exit behavior. There is no `appdata clean` or layout
migration command.

## Config editor

The Textual `ConfigEditorApp` displays registered settings, explanations,
effective values, and their contributing layers. It edits user or workspace
overrides through `ConfigManager`; a workspace registry is supplied separately
through `WorkspaceManager`. Opening the editor does not initialize application
state. Setup and save actions call managers explicitly.

## Gradio editor

`apprc_gui.ConfigEditor(manager, *, workspaces=None)` embeds settings controls
in an application-owned Gradio `Blocks`. `manager` is a `ConfigManager`.
Registry-backed workspace controls require the separate `WorkspaceManager`;
they fail clearly if it was not supplied. The editor does not build the
application runtime or initialize appdata/cache.


<br>

# Compose and ship applications

## Config bundles

A config bundle is a dataclass whose fields contain config sections. It is useful
when an application has several sections and wants to pass them together. For
example, `config.client.timeout` and `config.output.format` keep the API-client
and output settings separate while giving the application one object to pass
to its top-level function.

Register the dataclass with `@MyRC.bundle`. Give its fields the registered section
types and their normal default factories. `resolved.build(ApplicationConfig)`
constructs those sections using the same `ResolvedConfig`. A bundle is optional;
a small application can pass a single settings object directly.

The [bundle guide](How-To-User-Guides.md#pass-several-settings-sections-together)
builds two sections together. The
[larger application example](EXAMPLES.md#several-sections-and-temporary-overrides)
also shows how to pass the bundle to application code. Custom factories have
additional requirements described in [References](References.md#config-bundles).

## Imported dependency settings

An imported config binding connects one dependency's registered config section
to fields owned by a parent `AppRC`. This lets a host choose the names, defaults,
documentation, and secret metadata that appear in its own settings tools while
the dependency keeps its standalone namespace and config class.

The parent opts in with
[`AppRC.import_dependency_config()`](References.md#dependency-config-imports).
It selects one leaf section, declares the parent-owned fields, and maps the
dependency fields the host wants to expose. Several compatible fields can share
one parent field; for example, two model fields can use one host-selected model
name. Omitted dependency fields keep their Python defaults and are not added to
the parent's settings schema. Each parent can import the same dependency
section with a different map. The dependency class and its AppRC registration
are not changed.

In parent mode, AppRC reads values from the parent's resolved layers. It does
not use the dependency's ambient environment, user dotenv, workspace files, or
bundle registrations. Dependency packaged defaults are excluded unless the
parent opts in; selected values then sit below the parent's packaged defaults.
The parent's [field metadata and provenance](#provenance) describe the value
that the dependency receives.

When an imported section requires a workspace, the parent must declare
`workspaces=rc.Workspaces()` and select a valid parent workspace before building
that section. Inspection leaves its fields inactive until selection. The
parent's selected workspace layer can supply mapped settings; the dependency's
selector, registry, user files, workspace files, and layout bootstrap keys
remain excluded. The host passes any workspace paths required by the dependency
through its normal integration API.

`ResolvedConfig.build(binding)` constructs the dependency section from that
parent snapshot. A parent config bundle can also declare the dependency class as
a child; AppRC injects that child from the same snapshot. Calling the bundle's
constructor directly reports that an imported child requires the parent's
`ResolvedConfig`. The
[dependency-import guide](How-To-User-Guides.md#import-settings-from-a-dependency)
shows both forms. Imported instances cannot read the dependency's live process
environment through `reload()` or `bind_from_env()`; resolve the parent again
to build an updated instance, or use `reload_from()` with a snapshot containing
the same imported binding.

## Copies, overrides, and reloads

Settings objects are mutable Python objects with AppRC validation and provenance.
They are separate from the `ResolvedConfig` that supplied their inputs.
An explicit constructor argument or later assignment can change a field without
changing any dotenv file.

`settings.scoped(timeout=5)` creates a copy with a temporary override. This lets
one operation use a shorter timeout while other operations keep the original
settings. The [override guide](How-To-User-Guides.md#reload-settings-or-use-temporary-overrides)
demonstrates this with assertions.

`settings.reload_from(MyRC.resolve())` reads newly resolved inputs. AppRC validates
the candidate values before changing the settings object. By default, intentional
Python overrides remain authoritative; `override_python_values=True` also replaces
those. A failed reload keeps the previous values and provenance.

For dependencies that only read environment variables, `export_environment()`
provides an [explicit export operation](How-To-User-Guides.md#supply-settings-to-environment-only-code).
It changes the process environment. Normal `resolve()` and `build()` calls do not.

<a id="distribution-ownership"></a>
## Installed packages and installer builds

`apprc-core` provides the configuration and noninteractive management code.
`apprc` installs the matching core plus the dependencies for the CLI and Textual
editor. Both use `import apprc`. `apprc-gui` owns the Gradio editor and depends on
the same `apprc-core` version. The [installation instructions](../README.md#install)
explain which distribution to choose; maintainers can inspect the
[package ownership rules](Development.md#source-ownership).

AppRC does not build installers. An application declares its browser launcher
and CLI entry points and packages its own resources. It can build a Windows
`Setup.exe` containing Python and locked wheels, as described in the
[Windows installer guide](How-To-User-Guides.md#build-a-windows-installer).
The application controls its identity, shortcuts, and installed files.
