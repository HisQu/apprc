# AppRC reference

[Manual](README.md) · [Recipes](How-To-User-Guides.md) · [Architecture](Explanations.md)

- [Public namespaces](#public-namespaces)
- [Declarations](#declarations)
- [Resolution](#resolution)
- [Source precedence](#source-precedence)
- [Storage selection](#storage-selection)
- [Managed files](#managed-files)
- [Management](#management)
- [Provenance and lifecycle](#provenance-and-lifecycle)
- [Terminal commands](#terminal-commands)
- [Errors and write guarantees](#errors-and-write-guarantees)

## Public namespaces

| Import | Purpose |
| --- | --- |
| `rc.AppRC`, `rc.Config`, `rc.ConfigBase`, `rc.field` | Declaration and typed settings |
| `rc.UserDotenv`, `rc.Storage` | Independent persistence capabilities |
| `rc.ResolveOptions`, `rc.ResolvedConfig` | Invocation choices and captured inputs |
| `rc.schema` | Registered field and owner metadata, including `owner_for()` |
| `rc.provenance` | Field origin records and inspection helpers |
| `rc.files` | File result/error types and dotenv reads |
| `rc.storage` | Registry/selection types and read-only inspection helpers |
| `rc.cli` | Typer integration, CLI state, and diagnostic rendering |
| `rc.tui` | `ConfigEditorApp`, `ConfigSetupApp` |
| `apprc.scaffold` | `ConfigScaffoldRequest`, `scaffold_config_package()` |

Raw managed mutations are not exported from `rc.files` or `rc.storage`. Obtain
an application-bound manager with `MyRC.manage()`.

The core distribution owns all `apprc` Python modules, including lazily loaded
interface modules. Importing the core APIs does not import terminal libraries.
Using `rc.cli` operations or Textual classes requires the terminal distribution.
`apprc.interfaces` remains a compatibility namespace for interface exports; prefer
the explicit CLI or TUI namespace in new code.

## Declarations

`AppRC` takes keyword arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `app_id` | Required | Stable identity for paths and derived environment keys |
| `display_name` | `app_id` | Human-facing application name |
| `command_name` | `app_id` | Executable name in terminal instructions |
| `config_package` | `None` | Import package containing optional packaged defaults |
| `user_dotenv` | `None` | `UserDotenv()` enables user overrides |
| `storage` | `None` | `Storage()` enables named data roots |
| `apprc_dir` | `None` | Application-declared managed directory |
| `apprc_dir_env_key` | Derived | Override for the directory environment key |
| `legacy_app_ids` | `()` | Released identities accepted by migration |

`Storage(selector_env_key="DEMO_STORAGE")` overrides the derived storage key.
Neither capability has a `required` argument. Directory overrides require at
least one managed-file capability.

`@MyRC.config("app", prefix="DEMO_", title="App", rc_path=("app",))` registers a
section. The prefix is required for environment-backed sections. `rc.field()`
takes the complete environment key, with optional `default`, `default_factory`,
`required`, `secret`, `editable`, `choices`, `title`, `explanation_short`, and
`explanation_long`. Python types determine conversion and validation.

`@MyRC.bundle` registers a dataclass aggregate of registered section types.
`MyRC.schema` is immutable metadata for current registrations, including
`owners`, `envs`, identity, capabilities, and fixed filenames. It performs no
file writes and creates no interfaces.

## Resolution

`MyRC.resolve(options=None, *, environment=None)` returns `ResolvedConfig`.
`environment=None` captures `os.environ` once. An explicit mapping replaces that
input, including an empty mapping. Caller changes to the original mapping do not
change the resolution.

| `ResolveOptions` field | Default |
| --- | --- |
| `storage` | `None` |
| `storage_required` | `False` |
| `env_files` | `()` |
| `env_file_overrides_os_environ` | `False` |
| `load_dotenv_layers` | `True` |
| `apprc_dir` | `None` |

The frozen options copy `env_files` into a tuple of `Path` objects.

`ResolvedConfig` exposes `schema`, `options`, `values`, `source`, `layers`,
`paths`, `selection`, and `storage_count`. Raw values are immutable mappings.
`selection` is absent when no storage is selected. Its `root`, `storage_name`,
`raw_value`, `selector_kind`, and `source` describe the choice.

`resolved.build(Settings, **overrides)` constructs a registered section or bundle.
Required-field validation occurs here. Unknown types or types registered after
this resolution are rejected. Each call builds a fresh object.
`resolved.export_environment()` applies the deliberate overlay described in
[the export recipe](How-To-User-Guides.md#reload-and-export).

## Source precedence

Increasing priority, with later sources replacing earlier assignments:

1. Python field fallback, used when no source supplies the key.
2. Packaged `apprc.defaults.env`, if `config_package` is declared.
3. `apprc.user.env`, if user overrides are declared.
4. Selected storage's `apprc.storage.env`, if storage is selected.
5. Explicit `env_files`, in argument order.
6. Captured environment.

`env_file_overrides_os_environ=True` swaps the last two priorities. Constructor
arguments override source values for that object. Storage selection writes the
resolved root into the source snapshot's storage selector key after merging.

Each dotenv file interpolates against its earlier assignments and the captured
environment. Duplicate ordering, quoted values, bare keys, and `${NAME}` /
`${NAME:-fallback}` follow the supported dotenv parser behavior. A bare key does
not contribute a value; `KEY=` contributes an empty string. Parsing never swaps
`os.environ`.

`load_dotenv_layers=False` skips dotenv values for settings, but explicit files
still supply structural directory and storage inputs. Missing explicit files
are errors. Missing optional user/default files are empty layers.

![Runtime inputs and construction](assets/apprc-runtime-layers.svg)

## Storage selection

Increasing precedence is not used to discover storage from every dotenv layer.
The selector must be known before reading storage-local values.

Selection priority is:

1. `ResolveOptions.storage`, or CLI `--storage`.
2. Captured storage environment key, such as `DEMO_STORAGE`.
3. That key in explicit dotenv files.
4. `selected_storage` in `apprc.toml`.

The explicit-file override option swaps items 2 and 3. Packaged defaults, user
dotenv, and storage dotenv never choose storage. An invocation selector may be a
registered name or a directory path. Runtime requires a selected root to exist
with its fixed storage dotenv. A direct path can work without a valid registry.

No selection is allowed by default. `storage_required=True` rejects its absence;
it does not change the declaration. A supplied invalid selector always fails.
A required field representing a storage path can independently prevent object
construction even when invocation storage is optional.

Editor browsing, invocation selection, and the registry's saved default are
separate choices.

## Managed files

| File | Location and purpose |
| --- | --- |
| `apprc.defaults.env` | Packaged defaults inside `config_package` |
| `apprc.user.env` | Saved user overrides in the managed directory |
| `apprc.toml` | Storage registry in the managed directory |
| `apprc.storage.env` | Overrides and initialization marker in each storage root |

The managed-directory default is `~/.local/share/<app_id>` on supported platforms.
Priority is invocation `apprc_dir`, then the directory key in captured
inputs, then declaration `apprc_dir`, then the default. Explicit-file/environment
priority follows `env_file_overrides_os_environ`. For `app_id="demo-app"`, derived
keys are `DEMO_APP_APPRC_DIR` and `DEMO_APP_STORAGE`.

An existing file cannot enable an undeclared capability. Managed filenames are
fixed. The registry retains its existing `selected_storage`, `[storages.NAME]`
with `root`, and archive records. API migration does not rewrite it.

![Managed file locations](assets/apprc-storage-config-locations.svg)

## Management

`MyRC.manage(options=None, *, environment=None)` captures declaration and input
choices without writing. Each operation reads current files; it does not mutate
previous resolutions.

| Read or plan operation | Result |
| --- | --- |
| `paths` | Fixed managed paths, no directory creation |
| `resolve()` | Strict runtime source resolution |
| `inspect(storage=None, include_storage=True)` | `ConfigInspection` with fields, issues, and `ready` |
| `registry()` / `inspect_registry()` | Current registry or its readiness report |
| `writable_path(scope, storage=None)` | Declared edit target, independent of required field values |
| `writable_scopes()` / `resolve_write_scope(requested=None)` | Initialized scopes and ambiguity checking |
| `plan_update(reference, raw_value, scope=..., storage=None)` | Revision-bearing `EnvFileEditPlan` |
| `plan_removal(reference, scope=..., storage=None)` | Edit plan, or `None` when absent |
| `preview_edit(plan, storage=None)` | Effective candidate inspection without writing |
| `plan_migration(...)` / `plan_purge()` | Filesystem inventory for review |

`FieldInspection` carries `owner`, `field`, `value`, `origin`, and `issue`.
`display_value` redacts a declared secret. Inspection collects missing/invalid
fields and source readiness failures rather than constructing every runtime
object. It does not run application post-init validation.

Writing methods include `setup`, `setup_user_dotenv`, `apply_edit`, registry
mutations, directory/archive operations, `apply_migration`, and `apply_purge`.
See [operation effects](How-To-User-Guides.md#manage-storage).

## Provenance and lifecycle

`settings.provenance_of("retries")` returns a `ConfigProvenance` record. Shell
origins distinguish exported variables, packaged defaults, user/storage/explicit
dotenv, and `shell_storage_selector`. Python origins distinguish defaults,
constructor arguments, assignments, and scoped overrides.

File provenance retains its durable path. Packaged defaults also retain
`resource=(package_name, "apprc.defaults.env")`; archive resources have no extracted
temporary path. A direct constructor after environment export sees environment
provenance, not the original file.

`reload_from(resolved, override_python_values=False)` validates before committing.
`reload()` and `bind_from_env()` remain direct live-environment operations.
Copies and scoped overrides retain per-object provenance. Use `settings.scoped(retries=9)` for a cloned configuration with scoped overrides.

## Terminal commands

The `apprc` executable provides `scaffold config`. Application commands come from
`rc.cli.mount_config_cli(app, MyRC)` or `CliRuntime.mount_config_group(app)`.

| Application command | Availability and behavior |
| --- | --- |
| `config paths [--json]` | Always; read-only locations |
| `config doctor [--json]` | Always; readiness and suggested repairs |
| `config show [--json]` | Runtime payload; app serializer can use the snapshot |
| `config setup` | Declared persistence; prompts or `--yes` |
| `config set KEY VALUE [--scope user\|storage]` | Declared writable layers |
| `config edit` | Textual editor for declared persistence |
| `config migrate [--dry-run] [--yes]` | Explicit legacy migration |
| `config purge [--dry-run] [--yes]` | Reviewed managed-file cleanup |
| `config storage list/add/select/rename/repoint/move/remove` | Storage capability only |

Use application `--help` and subcommand help for exact option signatures.
`ConfigDoctorStatus` values are `runnable`, `config_invalid`,
`storage_not_selected`, `storage_not_ready`, `user_dotenv_not_ready`, and
`storage_registry_not_ready`. Doctor's JSON includes `writes="none"` and source
paths. `user_dotenv_required` remains a report field with value `False`.

## Errors and write guarantees

| Error | Meaning |
| --- | --- |
| `StorageSelectorError` | Supplied selector cannot resolve |
| `MissingStorageSelectorError` | Invocation requires storage but none is selected |
| `StorageNotInitializedError` | Chosen root lacks initialization |
| `StaleEditError` | Planned file revision differs from the current revision |
| `ConfigSetupError`, `ConfigMigrationError`, `ConfigPurgeError` | Operation-specific preflight or execution failure |

`StaleEditError` exposes `path`, `expected_revision`, and `actual_revision`.
Absence is a revision too, so a file created after planning is a conflict.
Atomic writes use unique same-directory temporary files and clean them after
failure. A shared lock serializes managed writes in one process. Cross-process
transactions and transactional directory deletion remain outside this guarantee.

An invalid field or failed resolution does not change files or process state.
Inspection can report incomplete configuration for repair. Application factories
and post-init hooks remain application code and can have their own effects.
