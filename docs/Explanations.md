# Explanations

[Documentation](README.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [AppRC](#apprc)
- [Config sections and fields](#config-sections-and-fields)
- [ResolvedConfig](#resolvedconfig)
- [Configuration layers](#configuration-layers)
- [Provenance](#provenance)
- [User dotenv and the AppRC directory](#user-dotenv-and-the-apprc-directory)
- [Storage](#storage)
- [Storage registry](#storage-registry)
- [ConfigManager](#configmanager)
- [Config CLI](#config-cli)
- [Config editor](#config-editor)
- [Config bundles](#config-bundles)
- [Copies, overrides, and reloads](#copies-overrides-and-reloads)
- [Installed packages and future integrations](#installed-packages-and-future-integrations)

This page explains AppRC's components in the order you need them. A small
application needs only an `AppRC`, a config section, and a `ResolvedConfig`.
Files, storage, and interactive tools can be added as the application grows.

<a id="declaration-resolution-and-management"></a>
## AppRC

`rc.AppRC` is the declaration of one application's configuration. Create it
once, usually in the application's `config/app.py`, and import that object
where the application declares or loads settings.

The declaration records the application's identity. For example,
`rc.AppRC(app_id="demo")` identifies settings as belonging to `demo`. If the
application later enables saved settings, AppRC uses that identity to derive
the directory and environment-variable names.

Register a [config section](#config-sections-and-fields) on this object with
`@MyRC.config(...)`. Registration tells AppRC which fields belong to the
application. It makes the same field definitions available to configuration
loading, the config editor, and diagnostic commands. Import the modules that
declare the sections before resolving settings.

An `AppRC` declaration does not hold the current value of every setting.
Its two main operations have different jobs:

| Operation | What it creates | What you use it for |
| --- | --- | --- |
| [`MyRC.resolve()`](References.md#resolution) | A [`ResolvedConfig`](#resolvedconfig) containing values read from the configured sources | [Build typed settings](How-To-User-Guides.md#read-typed-settings) for application code. |
| [`MyRC.manage()`](References.md#management) | A [`ConfigManager`](#configmanager) bound to this declaration | [Initialize or edit saved settings](How-To-User-Guides.md#save-a-user-preference) and manage data directories. |

The [basic settings example](EXAMPLES.md#settings-without-managed-files) uses
only `resolve()`. Both operations are useful in the
[user settings and storage example](EXAMPLES.md#user-settings-and-storage).

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
editor changes to a field controlled by the application. `secret=True` hides
a value in AppRC's display output. A secret value still exists in memory and
may be stored as plaintext in a dotenv file; this flag does not provide encryption
or a credential store. The [API-key guide](How-To-User-Guides.md#declare-an-api-key)
shows a required secret field.

Use `rc.ConfigBase` for Python-only sections that do not read environment keys.
Both kinds can be fields of a [config bundle](#config-bundles). A section is an
application grouping; it is not a separate dotenv file. The same file can supply
values for several sections.

## ResolvedConfig

`ResolvedConfig` is the result of reading configuration sources for one run.
`MyRC.resolve()` reads the enabled files and captures the process environment.
It records the selected storage, if there is one, and which source supplies each
value. It returns that information without writing files or changing `os.environ`.

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
the values it read. Selecting another storage also leaves earlier results
unchanged. This permits separate tests or application jobs to use different
settings in the same Python process.

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
| [User dotenv](#user-dotenv-and-the-apprc-directory) | Preferences saved for this user. |
| Selected [storage dotenv](#storage) | Settings saved with a particular data directory. |
| Explicit dotenv files | Extra inputs supplied for this invocation. |
| Process environment | Values inherited by the process, often exported by a shell or deployment system. |

For example, a timeout of `30` in Python, `20` in the user dotenv, and `10` in
the process environment produces `settings.timeout == 10`. Editing the user
dotenv to `15` still produces `10` while that environment value is present.
The [precedence example](EXAMPLES.md#explicit-dotenv-precedence) demonstrates this
with distinct values so the winning source is visible.

An application does not need all these layers. Packaged defaults require a
`config_package`; the user and storage files require their respective declarations.
The [dotenv guide](How-To-User-Guides.md#load-dotenv-files) shows how to supply an
explicit file without enabling saved user settings or storage.

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

<a id="capabilities-and-runtime-requirements"></a>
## User dotenv and the AppRC directory

The user dotenv is `apprc.user.env`, a file containing saved overrides for one
user of the application. Enable it with `user_dotenv=rc.UserDotenv()` on `AppRC`.
This is useful when a user changes a preference and expects it to survive the
next run without changing the application package.

The file lives in the AppRC directory, which defaults to
`~/.local/share/<app_id>`. For `app_id="demo"`, `DEMO_APPRC_DIR` relocates that
directory. The [managed-files reference](References.md#managed-files) explains
the other directory overrides. These paths are independent of the directory
from which the user launches the application.

Reading settings does not create the user dotenv. A missing file contributes no
overrides. The application can explicitly [save a user preference](How-To-User-Guides.md#save-a-user-preference)
through `ConfigManager`, or expose the [config editor](#config-editor) to users.
The [user preferences example](EXAMPLES.md#persistent-user-preferences) needs no storage.

## Storage

A storage is a persistent data directory used by the application. Enable storage
with `storage=rc.Storage()` on `AppRC`. A data directory can live outside the
source checkout and outside the installed package, so its location need not
change when the application is updated or run from another directory.

AppRC manages the directory's registration and its `apprc.storage.env` file.
The application decides what data to write there. For example, an export tool
can obtain the selected root and write `root / "report.txt"`. AppRC does not
intercept file writes or redirect arbitrary relative paths. The
[data-directory guide](How-To-User-Guides.md#store-data-outside-the-source-checkout)
shows the complete operation.

Each storage has its own dotenv file. A storage named `work` might use one API
endpoint while `personal` uses another. Selecting a storage selects both a data
directory and its configuration layer. A user dotenv, if enabled, supplies shared
preferences underneath those storage-specific overrides.

Declaring storage support does not force every operation to use it. An application
can show help without a selected storage, then require storage for an export job
with `ResolveOptions(storage_required=True)`. An explicitly supplied invalid
storage still fails. The [storage-only example](EXAMPLES.md#named-storage-without-user-overrides)
shows an operation that always needs storage.

Some config sections contain fields that only matter after storage selection.
Mark such a section with [`requires_storage=True`](References.md#declarations).
When no storage is selected, [`ConfigManager.inspect()`](References.md#management)
keeps its fields visible but marks them inactive and does not validate their
values. Other sections remain active, so `config doctor` can still report a bad
client setting. A runtime that needs the marked section must select storage
before building it.

## Storage registry

The storage registry is `apprc.toml` in the AppRC directory. It maps storage names
to paths and remembers the default selection. Giving directories names lets a
user select `work` rather than repeatedly typing its full path.

Three operations must be distinguished:

| Operation | Effect |
| --- | --- |
| Browse a storage in the config editor | Show that directory's settings without changing the saved default. |
| Supply `--storage work` or `ResolveOptions(storage="work")` | Choose `work` for this invocation. |
| [Select the saved default](How-To-User-Guides.md#register-and-switch-data-directories) | Update the registry so later runs can use `work` when no invocation choice overrides it. |

AppRC must select the directory before it can read that directory's dotenv file.
For that reason, the storage dotenv cannot select its own storage. The user
dotenv and packaged defaults also do not select storage. The
[selection reference](References.md#storage-selection) lists the exact priority.

The registry also supports [moving or reconnecting a directory](How-To-User-Guides.md#move-reconnect-or-archive-storage).
Moving tells AppRC to move the data. Reconnecting updates the recorded path after
the directory was moved elsewhere. Unregistering normally keeps the data.

<a id="interfaces-and-shared-operations"></a>
## ConfigManager

`ConfigManager`, returned by `MyRC.manage()`, performs operations on the files
declared by that `AppRC`. It gives Python code, the CLI, and the editor the same
setup and editing behavior. It does not display prompts itself.

Creating a manager does not write files. Each operation reads the files it needs.
`inspect()` reports available field values and individual problems, including
missing required values. `setup()` initializes the declared user dotenv or storage.
The [management reference](References.md#management) lists which methods read,
plan, or write.

An edit has an explicit review step. `plan_update()` validates the proposed value
and records the target file's revision. `preview_edit()` shows what the effective
settings would be. `apply_edit()` writes only if the file still matches the
recorded revision. The [edit guide](How-To-User-Guides.md#edit-or-remove-a-saved-override)
shows this sequence and how to handle a stale plan.

Editing a file does not change an earlier `ResolvedConfig` or settings object.
Resolve again to read the new file, then build or reload the settings needed by
the application. Writes use atomic file replacement, but operations across
multiple files or processes are not transactions. The
[write guarantees](References.md#errors-and-write-guarantees) state the limits.

## Config CLI

The config CLI is a group of Typer commands attached to the application's command
line. `rc.cli.mount_config_cli(app, MyRC)` adds the `config` group and the options
needed to choose inputs. It uses the same `AppRC` that registered the application's
config sections.

For example, `demo config doctor` inspects the settings, `demo config set` saves
an override, and `demo config edit` opens the config editor. Storage commands are
available when the declaration enables storage. [References](References.md#terminal-commands)
lists the commands and their availability.

The mounting function also resolves settings for application commands and places
the result in CLI state. A command obtains `state.resolved` and builds its settings
from it. The [Typer guide](How-To-User-Guides.md#add-configuration-commands-to-typer)
contains a complete runnable app. Applications that already own their root
callback can instead use the [custom-callback example](EXAMPLES.md#an-application-owned-cli-callback).

## Config editor

The config editor is AppRC's Textual terminal interface. It displays registered
settings, field explanations, effective values, and values from the contributing
configuration layers. Users can edit saved overrides in the user dotenv and
storage dotenv, and manage named storages from the same interface.

The editor displays packaged defaults and process-environment inputs for comparison.
It does not rewrite the installed defaults or the environment of the shell that
launched it. This distinction matters when an environment value overrides an edit
to a saved file. The [editor guide](How-To-User-Guides.md#inspect-and-edit-settings-in-the-terminal)
explains how to choose an edit target and recognize such an override.

Opening the editor writes nothing. Setup and save actions call `ConfigManager`
explicitly. The editor can open before all required values are valid so the user
can fix them. First-run setup is already implemented in the terminal; a desktop
GUI is [future work](#installed-packages-and-future-integrations).

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
## Installed packages and future integrations

`apprc-core` provides the configuration and noninteractive management code.
`apprc` installs the matching core plus the dependencies for the CLI and Textual
editor. Both use `import apprc`. The [installation instructions](../README.md#install)
explain which distribution to choose; maintainers can inspect the
[package ownership rules](Development.md#source-ownership).

<a id="future-desktop-and-build-integrations"></a>
A future Toga settings window can use the same `AppRC` field definitions and
`ConfigManager` operations as the terminal editor. It would provide widgets,
prompts, and graphical first-run setup. Coordination between simultaneous CLI
and GUI writes still needs implementation.

Future cx_Freeze tooling can package an application with the resources AppRC
expects and assemble installers. It belongs in build tooling, separate from the
code that reads settings while the application runs. Neither a Toga interface nor
native installer generation is implemented in this release.
