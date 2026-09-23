# References

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [Public namespaces](#public-namespaces)
- [Declarations](#declarations)
- [Config fields](#config-fields)
- [Config bundles](#config-bundles)
- [Resolution](#resolution)
- [Source precedence](#source-precedence)
- [Storage selection](#storage-selection)
- [Managed files](#managed-files)
- [Management](#management)
- [Storage operations](#storage-operations)
- [Provenance and lifecycle](#provenance-and-lifecycle)
- [Terminal commands](#terminal-commands)
- [Errors and write guarantees](#errors-and-write-guarantees)

## Public namespaces

Examples use `import apprc as rc`. These names belong to the public API:

| Import | Purpose |
| --- | --- |
| [`rc.AppRC`](Explanations.md#apprc) | Declare the application and register config sections. |
| [`rc.Config`, `rc.ConfigBase`, `rc.field`](Explanations.md#config-sections-and-fields) | [Define typed settings](How-To-User-Guides.md#read-typed-settings) and their documentation. |
| [`rc.UserDotenv`](Explanations.md#user-dotenv-and-the-apprc-directory) | Enable saved user overrides. |
| [`rc.Storage`](Explanations.md#storage) | Enable named persistent data directories. |
| [`rc.ResolveOptions`, `rc.ResolvedConfig`](Explanations.md#resolvedconfig) | Choose configuration inputs and build settings from them. |
| `rc.schema` | Read registered section and field metadata, including `owner_for()`. |
| [`rc.provenance`](Explanations.md#provenance) | Read field origin records and format them for inspection. |
| `rc.files` | Read dotenv files and access file result and error types. |
| `rc.storage` | Read registry and selection records; mutations go through [ConfigManager](Explanations.md#configmanager). |
| [`rc.cli`](Explanations.md#config-cli) | Add Typer commands, CLI state, and diagnostic output. |
| [`rc.tui`](Explanations.md#config-editor) | `ConfigEditorApp` and `ConfigSetupApp` terminal interfaces. |
| `apprc.scaffold` | `ConfigScaffoldRequest` and `scaffold_config_package()` for [generating a config package](How-To-User-Guides.md#generate-a-config-package). |

`apprc-core` owns the Python modules, including lazily imported terminal modules.
Using terminal implementations requires the `apprc` distribution's dependencies.
`apprc.interfaces` remains a compatibility import; new code should use `rc.cli`
or `rc.tui`. The [package explanation](Explanations.md#installed-packages-and-future-integrations)
describes why both distributions use the same import name.

## Declarations

[`rc.AppRC`](Explanations.md#apprc) takes keyword arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `app_id` | Required | Application identity used for the default directory and derived environment keys. |
| `display_name` | `app_id` | Human-readable application name. |
| `command_name` | `app_id` | Executable name printed in terminal instructions. |
| `config_package` | `None` | Import package containing optional [packaged defaults](How-To-User-Guides.md#ship-defaults-with-the-application). |
| `user_dotenv` | `None` | `UserDotenv()` enables the [user dotenv](Explanations.md#user-dotenv-and-the-apprc-directory). |
| `storage` | `None` | `Storage()` enables [storage](Explanations.md#storage). |
| `apprc_dir` | `None` | Explicit application default for the [AppRC directory](#managed-files). |
| `apprc_dir_env_key` | Derived | Override the environment key used to relocate the AppRC directory. |
| `legacy_app_ids` | `()` | Previous application identities accepted by [migration](How-To-User-Guides.md#migrate-existing-applications). |

`Storage(selector_env_key="DEMO_STORAGE")` overrides the derived storage key.
Neither `Storage` nor `UserDotenv` takes `required`. Require storage for a run
through [ResolveOptions](#resolution). Directory overrides on the declaration
require at least one of `UserDotenv()` or `Storage()`.

`@MyRC.config("client", prefix="DEMO_", title="Client", rc_path=("client",))`
registers a [config section](Explanations.md#config-sections-and-fields).
`prefix` is required for an environment-backed section, and each field's full
environment key must use that prefix. Import sections before resolving.
`MyRC.schema` contains immutable metadata for the current registrations, including
`owners`, `envs`, application identity, enabled features, and fixed filenames.
Reading the schema does not load configuration values or write files.

## Config fields

[`rc.field()`](Explanations.md#config-sections-and-fields) declares one field in a
`Config` section. Python annotations determine conversion and validation.

| Argument | Meaning |
| --- | --- |
| First positional argument | Complete environment key, for example `DEMO_TIMEOUT`. |
| `default` / `default_factory` | Python fallback when no source supplies a value. Use only one. |
| `required` | Require a value. A field without a fallback is required by default; `required=True` cannot be combined with a Python fallback. |
| `choices` | Accepted string values, supplied as a sequence. |
| `title` | Human-readable field label. |
| `description` | Shared fallback text for short and long explanations. |
| `explanation_short` | Compact explanation used in tables. |
| `explanation_long` | Longer explanation used in the editor; falls back to `description`, then the short explanation. |
| `editable` | Whether the standard editor permits direct edits; defaults to `True`. |
| `secret` | Redact display values; defaults to `False`. Does not encrypt persisted values. |
| `packaged_default` | Metadata describing an expected packaged default; does not supply the runtime value. |

The [typed-settings guide](How-To-User-Guides.md#read-typed-settings) demonstrates
conversion, and the [API-key guide](How-To-User-Guides.md#declare-an-api-key)
demonstrates required and secret fields. Required values are checked by
`ResolvedConfig.build()`; [inspection](#management) can report missing fields
before settings objects can be constructed.

## Config bundles

A [config bundle](Explanations.md#config-bundles) is a keyword-only dataclass
registered with `@MyRC.bundle`. Place `@dataclass(kw_only=True)` immediately below
`@MyRC.bundle`. Declare each child with its registered config-section type and
`field(default_factory=SectionType)`.

`resolved.build(BundleType)` constructs those section factories from the same
`ResolvedConfig`. Unregistered section types are rejected. Normal Python-only
factories and dataclass post-init hooks retain their ordinary behavior. For a
custom factory that constructs an environment-backed section, pass the child
explicitly as `resolved.build(BundleType, client=resolved.build(ClientSettings))`
so it receives the intended configuration sources.

The [bundle guide](How-To-User-Guides.md#pass-several-settings-sections-together)
provides a complete two-section example. The [larger example](EXAMPLES.md#several-sections-and-temporary-overrides)
also exercises section overrides and reloads.

## Resolution

`MyRC.resolve(options=None, *, environment=None)` returns a
[`ResolvedConfig`](Explanations.md#resolvedconfig). `environment=None` captures
`os.environ` once; an explicit mapping replaces that input. `{}` excludes the
process environment. Later changes to the caller's mapping do not change the result.

| `ResolveOptions` field | Default | Behavior |
| --- | --- | --- |
| `storage` | `None` | Invocation's storage name or directory path; [selection rules](#storage-selection) apply. |
| `storage_required` | `False` | Reject a run without selected storage. |
| `env_files` | `()` | Explicit dotenv files, read in order; demonstrated in the [dotenv guide](How-To-User-Guides.md#load-dotenv-files). |
| `env_file_overrides_os_environ` | `False` | Put explicit files above process environment values. |
| `load_dotenv_layers` | `True` | Load dotenv values into settings. When false, explicit files still supply directory and storage selection inputs. |
| `apprc_dir` | `None` | Invocation override for the AppRC directory. |

Options are frozen; `env_files` is normalized to a tuple of `Path` objects.

| `ResolvedConfig` member | Meaning |
| --- | --- |
| `schema` | Declaration metadata captured for this result. |
| `options` | Resolution options used. |
| `values` | Immutable mapping of effective source values; may contain secrets. |
| `source` | Effective source values with origin records. |
| `layers` | Individual source records retained for inspection. |
| `paths` | Managed file locations for this run, or `None` without managed-file features. |
| `selection` | Selected storage record, or `None`; includes `root`, `storage_name`, `raw_value`, `selector_kind`, and `source`. |
| `storage_count` | Number of registered storages read during resolution. |
| `build(Type, **overrides)` | Construct a fresh registered section or bundle; convert and validate its fields. |
| `export_environment()` | [Write selected values to the process environment](How-To-User-Guides.md#supply-settings-to-environment-only-code). |

`build()` rejects types unknown to this result, including types registered after
resolution. It does not reread files. Constructor overrides affect that object
only. The [basic example](EXAMPLES.md#settings-without-managed-files) demonstrates
independent results.

## Source precedence

[Configuration layers](Explanations.md#configuration-layers) apply in increasing
priority, with later values replacing earlier assignments:

1. Python field fallback, when no source supplies the key.
2. Packaged `apprc.defaults.env`, if `config_package` is declared.
3. `apprc.user.env`, if user overrides are declared.
4. Selected storage's `apprc.storage.env`.
5. Explicit `env_files`, in argument order.
6. Captured process environment.

`env_file_overrides_os_environ=True` swaps the last two priorities. Constructor
arguments override source values for that object. AppRC records the selected
storage root in the result's storage selector key after merging. The
[precedence example](EXAMPLES.md#explicit-dotenv-precedence) shows both priority orders.

Each dotenv file interpolates against its earlier assignments and the captured
environment. `${NAME}` and `${NAME:-fallback}` are supported. A bare key supplies
no value; `KEY=` supplies an empty string. Parsing never swaps `os.environ`.
Missing explicit files are errors. Missing optional user or packaged-default
files contribute no values. `load_dotenv_layers=False` still reads explicit files
for directory and storage selection, while excluding their setting values.

## Storage selection

The [storage registry](Explanations.md#storage-registry) records available names
and the saved default. Selection priority is:

1. `ResolveOptions.storage`, or CLI `--storage`.
2. Captured storage environment key, such as `DEMO_STORAGE`.
3. That key in explicit dotenv files.
4. `selected_storage` in `apprc.toml`.

The explicit-file override option swaps items 2 and 3. Packaged defaults, user
dotenv, and storage dotenv do not choose storage. A selector can be a registered
name or directory path. The selected directory must exist and contain a readable
`apprc.storage.env`. An initialized direct path can work without a valid registry.
Relative selector paths resolve relative to the registry's directory.

No selection is allowed by default. `storage_required=True` rejects absence;
an invalid supplied selector always fails. A required config field representing
the storage path can independently prevent construction even when the invocation
does not require storage.

[Browsing, invocation selection, and the saved default](Explanations.md#storage-registry)
have different effects. The [switching guide](How-To-User-Guides.md#register-and-switch-data-directories)
demonstrates the distinction with assertions.

## Managed files

| File | Location and purpose |
| --- | --- |
| `apprc.defaults.env` | Inside `config_package`; [ship application defaults](How-To-User-Guides.md#ship-defaults-with-the-application). |
| `apprc.user.env` | In the [AppRC directory](Explanations.md#user-dotenv-and-the-apprc-directory); [save user preferences](How-To-User-Guides.md#save-a-user-preference). |
| `apprc.toml` | In the AppRC directory; [storage registry](Explanations.md#storage-registry). |
| `apprc.storage.env` | In each [storage](Explanations.md#storage); overrides and initialization marker. |

The default AppRC directory is `~/.local/share/<app_id>` on supported platforms.
Priority is invocation `apprc_dir`, then the directory environment key in captured
inputs, then declaration `apprc_dir`, then the default. Explicit-file/environment
priority follows `env_file_overrides_os_environ`. For `app_id="demo-app"`, the
derived keys are `DEMO_APP_APPRC_DIR` and `DEMO_APP_STORAGE`.

Managed filenames are fixed. The registry uses `selected_storage`,
`[storages.NAME]` entries with `root`, and archive records. An existing file cannot
enable an undeclared feature. The [combined example](EXAMPLES.md#user-settings-and-storage)
shows how user and storage files coexist.

## Management

`MyRC.manage(options=None, *, environment=None)` creates a
[`ConfigManager`](Explanations.md#configmanager) without writing. Each operation
reads current files; previous `ResolvedConfig` objects remain unchanged.

| Operation | Result or effect |
| --- | --- |
| `paths` | Managed file locations without creating directories. |
| `resolve()` | Strict configuration resolution using the manager's options and environment. |
| `inspect(storage=None, include_storage=True)` | `ConfigInspection` with `fields`, `issues`, and `ready`; [diagnose incomplete settings](How-To-User-Guides.md#troubleshoot-configuration). |
| `registry()` / `inspect_registry()` | Current registry or its readiness report. |
| `writable_path(scope, storage=None)` | Target path for a declared write scope. |
| `writable_scopes()` / `resolve_write_scope(requested=None)` | Initialized scopes; reject an ambiguous automatic choice. |
| `plan_update(reference, raw_value, scope=..., storage=None)` | Validated `EnvFileEditPlan` with target revision. |
| `plan_removal(reference, scope=..., storage=None)` | Removal plan, or `None` if the assignment is absent. |
| `preview_edit(plan, storage=None)` | Candidate inspection without writing; [preview a saved override](How-To-User-Guides.md#edit-or-remove-a-saved-override). |
| `apply_edit(plan)` | Write an edit after checking its revision. |
| `setup(storage_root=None, storage_name="default")` | Initialize declared files; storage declarations require a root. |
| `setup_user_dotenv()` | Initialize just the user dotenv, even when storage is also enabled. |
| `plan_migration(...)` / `apply_migration(plan)` | Review and apply supported legacy-file migration. |
| `plan_purge()` / `apply_purge(plan)` | Review and remove managed files and registered internal storage data. |

A field reference can be a dotted registered path, an unambiguous field name,
or the complete environment key. Write scope is `"user"` or `"storage"`.
Explicit user edits can create a missing user dotenv; storage edits require an
initialized storage. Setup preserves existing files and does not recreate a
missing registered storage root or repoint an existing name.

`FieldInspection` exposes `owner`, `field`, `value`, `origin`, and `issue`.
Its `display_value` redacts secrets. Inspection reports field conversion and
source problems without constructing every runtime object; it does not execute
application post-init validation. The [saved-preference guide](How-To-User-Guides.md#save-a-user-preference)
provides a complete setup and editing sequence.

Purge removes fixed AppRC files and registered data directories strictly inside
the AppRC directory. For external storages it removes the marker dotenv and
retains application data. It does not follow symlinks. Review the purge plan
before applying it.

## Storage operations

All methods belong to [`ConfigManager`](Explanations.md#configmanager).
The [directory-switching guide](How-To-User-Guides.md#register-and-switch-data-directories)
and [storage-lifecycle guide](How-To-User-Guides.md#move-reconnect-or-archive-storage)
provide independent runnable examples.

| Method | Data effect |
| --- | --- |
| `register_storage(name, root)` | Create or register a root and its storage dotenv. |
| `select_storage(name)` | Change the registry's saved default for future runs. |
| `rename_storage(current_name, name)` | Change the registered name. |
| `repoint_storage(name, root)` | Record an existing initialized directory; move no data. |
| `move_storage(name, destination)` | Move data to a new or empty destination with preflight checks and rollback. |
| `remove_storage(name)` | Unregister and retain the directory contents. |
| `remove_storage(name, delete_content=True)` | Unregister and then delete the directory contents. |
| `archive_storage(name, archive_path)` | Create and record an archive; retain the live directory. |
| `restore_storage(name, archive_path, destination)` | Extract and register; roll back extraction if registration fails. |
| `remove_archive_record(name)` | Forget the record; retain the archive file. |

Archive filenames must end in `.apprc.tar.xz`.

These are not complete filesystem transactions. Directory deletion can fail after
unregistration; inspect the remaining directory and registry before retrying.

## Provenance and lifecycle

[`settings.provenance_of("timeout")`](Explanations.md#provenance) returns
`ConfigProvenance`. The [inspection guide](How-To-User-Guides.md#find-where-a-value-came-from)
checks a file origin directly.

| Field | Meaning |
| --- | --- |
| `field_name` | Python field name. |
| `source` | `"python"` or `"shell"`; dotenv origins also use `"shell"`. |
| `origin` | Exact origin identifier, such as `shell_dotenv_user` or `python_constructor_argument`. |
| `value` / `display_value` | Actual value / redacted display value. |
| `secret` | Whether the field is declared secret. |
| `env_key` | Environment key, when applicable. |
| `path` | Durable source-file path, when applicable. |
| `resource` | Package and resource name for packaged defaults. |

Shell origin identifiers are `shell_export_variable`, `shell_dotenv_defaults`,
`shell_dotenv_user`, `shell_dotenv_storage`, `shell_dotenv_explicit`, and
`shell_storage_selector`. Python origins distinguish config and Python-only
defaults, constructor arguments, runtime assignments, scoped overrides, and
process-environment mutations.

Packaged defaults retain `resource=(package_name, "apprc.defaults.env")`.
An archive resource has no extracted temporary path. A direct constructor after
explicit environment export sees environment provenance rather than its original
file source.

`reload_from(resolved, override_python_values=False)` validates before changing
the object. By default, constructor arguments, assignments, and scoped overrides
remain authoritative. `reload()` and `bind_from_env()` read the live process
environment. Copies and [`scoped()` overrides](How-To-User-Guides.md#reload-settings-or-use-temporary-overrides)
retain per-object provenance.

## Terminal commands

The [`config CLI`](Explanations.md#config-cli) is mounted with
`rc.cli.mount_config_cli(app, MyRC)` or `CliRuntime.mount_config_group(app)`.
The standalone `apprc` executable provides `scaffold config`.

| Application command | Availability and behavior |
| --- | --- |
| `config paths [--json]` | Always; report locations without writing. |
| `config doctor [--json]` | Always; report readiness and [repair guidance](How-To-User-Guides.md#troubleshoot-configuration). |
| `config show [--json]` | Show runtime configuration; an application serializer can read `state.resolved`. |
| `config setup` | Declared persistence; [initialize files](How-To-User-Guides.md#save-a-user-preference) interactively or with `--yes`. |
| `config set KEY VALUE [--scope user\|storage]` | Edit a declared writable layer. |
| `config edit` | Open the [config editor](Explanations.md#config-editor) for declared persistence. |
| `config migrate [--dry-run] [--yes]` | Migrate supported legacy files explicitly. |
| `config purge [--dry-run] [--yes]` | Review or apply managed-file cleanup. |
| `config storage list/add/select/rename/repoint/move/remove` | Manage registered storages when storage is declared. |

Root options precede the subcommand: `--env-file`,
`--env-file-overrides-os-environ`, `--skip-dotenv-layers`, `--storage` when enabled,
and `--log-level`. Use the application's `--help` for each command's arguments.
The [Typer guide](How-To-User-Guides.md#add-configuration-commands-to-typer)
shows mounting and retrieving state; the [custom-callback example](EXAMPLES.md#an-application-owned-cli-callback)
shows `CliRuntime` integration.

`ConfigDoctorStatus` values are `runnable`, `config_invalid`,
`storage_not_selected`, `storage_not_ready`, `user_dotenv_not_ready`, and
`storage_registry_not_ready`. Doctor JSON includes `writes="none"` and source
paths. `user_dotenv_required` remains a report field with value `False`.

## Errors and write guarantees

| Error | Meaning and recovery |
| --- | --- |
| `StorageSelectorError` | Supplied selector cannot resolve; check the [selection rules](#storage-selection). |
| `MissingStorageSelectorError` | This invocation requires storage but none is selected; [register or select one](How-To-User-Guides.md#register-and-switch-data-directories). |
| `StorageNotInitializedError` | Selected directory lacks initialization; inspect it before setup. |
| `StaleEditError` | File revision changed; [make a fresh edit plan](How-To-User-Guides.md#edit-or-remove-a-saved-override). |
| `ConfigSetupError`, `ConfigMigrationError`, `ConfigPurgeError` | Operation-specific preflight or execution failure; inspect the reported paths and remaining files. |

`StaleEditError` exposes `path`, `expected_revision`, and `actual_revision`.
Absence is a revision too: a file created after planning is a conflict.
Writes use unique same-directory temporary files and atomic replacement, with
cleanup after failure. A shared lock serializes managed writes within one process.
Cross-process transactions and transactional directory deletion are not provided.

A failed resolution or field conversion does not change files or process state.
Application factories and post-init hooks are application code and can have their
own effects. The [ConfigManager explanation](Explanations.md#configmanager)
separates inspection, planning, and application of a change.
