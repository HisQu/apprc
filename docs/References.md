# References

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [Examples](EXAMPLES.md) · [Development](Development.md)

- [Python API](#python-api)
  - [Public namespaces](#public-namespaces)
  - [Declarations](#declarations)
  - [Config fields](#config-fields)
  - [Application paths](#application-paths)
  - [Layout bootstrap](#layout-bootstrap)
  - [Resolution](#resolution)
  - [Workspace selection](#workspace-selection)
  - [Config bundles](#config-bundles)
  - [Dependency config imports](#dependency-config-imports)
- [Value sources and files](#value-sources-and-files)
  - [Source precedence](#source-precedence)
  - [Managed files](#managed-files)
- [Management and lifecycle](#management-and-lifecycle)
  - [ConfigManager](#configmanager)
  - [WorkspaceManager](#workspacemanager)
  - [Maintenance](#maintenance)
  - [Provenance and lifecycle](#provenance-and-lifecycle)
- [Commands and errors](#commands-and-errors)
  - [Terminal commands](#terminal-commands)
  - [Errors and write guarantees](#errors-and-write-guarantees)

<br>

# Python API

## Public namespaces

Examples use `import apprc as rc`.

| Import | Purpose |
| --- | --- |
| `rc.AppRC` | Declare an application and register config sections. |
| `rc.Config`, `rc.ConfigBase`, `rc.field` | Define typed settings and field documentation. |
| `rc.Paths`, `rc.Layout`, `rc.AppPaths` | Declare, choose, and inspect independent filesystem paths. |
| `rc.UserDotenv` | Enable saved user preferences; requires config enabled. |
| `rc.Workspaces`, `rc.WorkspaceManager` | Declare and manage selectable working directories. |
| `rc.ResolveOptions`, `rc.ResolvedConfig` | Choose inputs and construct settings from a snapshot. |
| `rc.MaintenanceHandlers`, `rc.RemovalPlan`, `rc.RemovalResult` | Supply and report supported category operations. |
| `rc.schema`, `rc.provenance`, `rc.files` | Inspect declaration metadata, provenance, and dotenv parsing. |
| `rc.workspaces` | Read workspace records and registry helpers. |
| `rc.cli`, `rc.tui` | Typer adapters and Textual interfaces. |
| `apprc_gui.ConfigEditor` | Optional Gradio editor. |
| `apprc.scaffold` | `ConfigScaffoldRequest` and `scaffold_config_package()`. |

`apprc-core` owns the `apprc` modules; terminal use requires the `apprc`
distribution. `apprc-gui` provides `apprc_gui`. New code uses the public
`rc.cli` and `rc.tui` namespaces.

## Declarations

`rc.AppRC` accepts keyword arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `app_id` | Required | Must fully match `[A-Za-z0-9][A-Za-z0-9_.-]*`; `.` and `..` are invalid. Also derives environment prefixes. |
| `display_name`, `command_name` | `app_id` | Human-facing name and executable label. |
| `paths` | `Paths()` | Independently enable `config`, `appdata`, `cache`, and `state`. |
| `layout` | `None` | Declared `Layout`; `None` means default native layout. |
| `bootstrap_env_prefix` | Derived from normalized `app_id` | Prefix for layout/root bootstrap controls. |
| `user_dotenv` | `None` | `UserDotenv()` enables saved user config; requires `paths.config=True`. |
| `workspaces` | `None` | `Workspaces(selector_env_key=None, registry=True)` enables workspace selection. Registry mode requires config enabled. |
| `config_package` | `None` | Package containing optional `apprc.defaults.env`. |
| `setup_next_step` | `None` | Text printed after successful explicit config setup. |

`Paths(config=False, appdata=False, cache=False, state=False)` is a declaration.
`Layout` is `Layout(mode="native", root=None)`, `Layout.native()`, or
`Layout.single_root(root)`. `AppRC.paths(options=None, *, environment=None)`
returns a read-only `AppPaths`. `AppRC.ensure_path(kind, options=None, *,
environment=None, adopt=False)` creates and owns only the requested enabled
path. `kind` is one of `config`, `appdata`, `cache`, `state`, or subordinate
`logs`. `AppPaths.require(kind)` returns its `Path` or raises
`ValueError("AppRC path component '<kind>' is not enabled.")`.

`@MyRC.config(key, prefix=..., title=None, rc_path=None)` registers a config
section. `requires_workspace=True` marks fields inactive until a workspace is
selected; the declaration must enable `workspaces`. Schema inspection does not
read values or create files. Config sections and field semantics are described
in [Explanations](Explanations.md#config-sections-and-fields).

## Config fields

`rc.field(env_key, ...)` declares one field on a registered `Config` section.
The Python annotation controls conversion and validation.

| Argument | Meaning |
| --- | --- |
| `env_key` | Complete environment key, for example `DEMO_TIMEOUT`. |
| `default` / `default_factory` | Python fallback; use only one. |
| `required` | Require an input; a field without a fallback is required by default. |
| `choices` | Accepted string values. |
| `title`, `description` | Human-readable field label and shared explanatory text. |
| `explanation_short`, `explanation_long` | Compact table text and longer editor guidance. |
| `editable` | Whether the standard editor permits direct edits; defaults to true. |
| `restart_required` | Mark that the saved change takes effect only after application restart. |
| `secret` | Redact display output and use the private layer companion; does not encrypt values. |
| `packaged_default` | Metadata describing an expected packaged default; does not supply the value. |

Required values are checked by `ResolvedConfig.build()`. Read-only inspection
can report missing values before application settings are constructed.

## Application paths

`AppPaths` is a frozen snapshot with `layout`, `source` (`invocation`,
`environment`, `declaration`, or `default`), and `config_dir`, `appdata_dir`,
`cache_dir`, `state_dir`, and `logs_dir`. Disabled locations are `None`; disabled
state also means disabled logs. `ResolvedConfig.paths` always contains this
record, including all-`None` records.

Native mode uses platformdirs user locations and accesses only enabled category
properties. Linux uses the selected config/data/cache/state/log properties
directly. Windows and macOS append app-specific config, appdata, and state
directories to their category bases; cache and logs use their native properties.
Disabled state means neither state nor log properties are accessed.
Single-root mode maps enabled categories to `root/config`, `root/appdata`,
`root/cache`, and `root/state`; logs are `root/state/logs`.
`Layout.single_root` expands `~` and resolves relative roots against invocation
current working directory once. It never uses package location.

Path inspection creates no directories and repairs no ownership. Initialization
uses `.apprc-owner.json` with exactly `schema_version: 1`, `app_id`, and
`category`. Mutation refuses links/reparse points, overlapping managed roots,
mismatched markers, and nonempty unowned directories unless explicit adoption
is requested. Adoption claims contents; it does not move or delete them. Config
setup uses the same initializer, and `config init --adopt` explicitly adopts an
existing nonempty config root. Ordinary edits never silently adopt. `ensure_path("state")`
does not initialize logs; `ensure_path("logs")` does. State maintenance returns
separate plans for distinct state/log roots and deduplicates nested roots.

No old location is scanned as a fallback. A path declaration does not enable
UserDotenv, Workspaces, or a maintenance provider. AppRC does not move or delete
old user files during upgrades.

## Layout bootstrap

Controls are `<PREFIX>_LAYOUT` and `<PREFIX>_ROOT`; `<PREFIX>` is normalized
`app_id` unless `bootstrap_env_prefix` overrides it. Invocation `Layout` wins.
Otherwise AppRC selects the highest raw input layer containing either nonblank
control, then interprets that layer's pair as a unit. Root alone means
single-root; `native` plus root in that selected layer is an error; higher-layer
`native` ignores a lower-layer root. Declaration layout and then default native
are fallback layers.

Process environment normally outranks explicit dotenv files, considered in
reverse argument order; `env_file_overrides_os_environ=True` reverses this
precedence. Each explicit file is its own raw layer. Scalar config/workspace
selection uses merged `selection_env`; the layout pair does not. Managed dotenv
cannot relocate itself. `AppPaths.source` records the selected layer. Imported
dependency resolution excludes that dependency's bootstrap and workspace keys.

## Resolution

`MyRC.resolve(options=None, *, environment=None)` returns a `ResolvedConfig`.
`environment=None` captures process environment; an explicit mapping replaces
it, and `{}` excludes process variables. Options are frozen and normalize
`env_files` to a tuple of paths.

| `ResolveOptions` field | Default | Behavior |
| --- | --- | --- |
| `workspace` | `None` | Invocation workspace name or direct directory path. |
| `workspace_required` | `False` | Reject an invocation without a selected workspace. |
| `layout` | `None` | Invocation override for the complete layout selection; `--layout` and `--app-root` are CLI forms. |
| `env_files` | `()` | Explicit dotenv layers, read in argument order. |
| `env_file_overrides_os_environ` | `False` | Put explicit files above process environment, for scalar inputs and bootstrap-layer precedence. |
| `load_dotenv_layers` | `True` | Load dotenv values as settings; explicit files still participate in selectors. |

`ResolvedConfig` contains `schema`, `options`, immutable `values`, `source`,
`layers`, `paths: AppPaths`, `workspace`, and `workspace_issues`, plus
`build(Type, **overrides)` and `export_environment()`. `build()` rejects types
not registered in that snapshot and never rereads inputs. Invalid ordinary
fields can be reported by inspection without preventing path inspection or
category-only maintenance. Refreshing settings retains the originally captured
paths and their provenance.

## Workspace selection

`Workspaces(selector_env_key=None, registry=True)` uses
`<PREFIX>_WORKSPACE` by default. Registry mode requires config enabled and reads
`apprc.toml` with `schema_version = 1`, `selected_workspace`,
`[workspaces.NAME] root = ...`, and archive records under
`[archived_workspaces.NAME]`. Old `storages` keys are rejected, not upgraded.

Selection priority is invocation `ResolveOptions.workspace`/CLI `--workspace`,
then selector in the winning scalar environment/file inputs, then saved
Workspace dotenv cannot select itself. In direct mode, relative paths supplied
as workspace selectors resolve against invocation current working directory; a
bare selector name raises `ValueError("Named workspaces require a registry.")`.
`WorkspaceManager.initialize_workspace(root)` accepts an explicit path argument,
including a bare relative `Path("demo-workspace")`, to create the workspace's
`apprc.workspace.env`; it does not write config or registry files, or create a
secret companion. `workspace init PATH` exposes this operation in the CLI.
Selection changes workspace overlay/root only, never `AppPaths`.

Direct mode does not persist registration.

## Config bundles


A config bundle is a keyword-only dataclass registered with `@MyRC.bundle`.
Place `@dataclass(kw_only=True)` immediately beneath that decorator. Its fields
use registered config section types and `field(default_factory=SectionType)`.
`resolved.build(BundleType)` builds registered children from the same snapshot.
For an environment-backed custom child factory, pass the child explicitly:
`resolved.build(BundleType, client=resolved.build(ClientSettings))`. Unregistered
section types are rejected. Normal Python-only factories and dataclass
post-init hooks retain ordinary behavior.

## Dependency config imports

`MyRC.import_dependency_config(dependency, ConfigType, *, key, prefix, fields,
field_targets=None, title=None, rc_path=None, include_packaged_defaults=False)`
binds one registered dependency section to parent-owned fields.

The parent owns defaults, validation, docs, and secret metadata. `fields` maps
parent field names to `rc.field(...)`; `field_targets` maps dependency field
names to parent field names. Omitted dependency fields retain their Python
defaults and are not registered in the parent schema. Every parent field must
be used, mapped types must match, and dependency secrets must remain secret.
Dependency packaged defaults are excluded unless explicitly opted in.

The dependency's ambient environment, explicit dotenv keys, user files,
workspace files, workspace selector, registry, and layout bootstrap keys are
excluded. If the imported section requires a workspace, the parent must declare
and select one before building it. `resolved.build(binding)` uses the binding
captured by that exact snapshot. A bundle may declare the imported section as a
child; AppRC injects that child from the parent's snapshot. See the
[dependency-import guide](How-To-User-Guides.md#import-settings-from-a-dependency).
<br>

# Value sources and files

## Source precedence

Setting values apply in increasing priority:

1. Python field fallback.
2. Packaged `apprc.defaults.env`.
3. User `apprc.user.env`.
4. User `apprc.user.secret.env` for declared secret fields.
5. Selected workspace `apprc.workspace.env`.
6. Selected workspace `apprc.workspace.secret.env` for declared secret fields.
7. Explicit `env_files` in argument order.
8. Captured process environment.

`env_file_overrides_os_environ=True` swaps the final two priorities. Constructor
arguments override source values for the constructed settings object. Dotenv
interpolation supports `${NAME}` and `${NAME:-fallback}`; a bare key supplies no
value, while `KEY=` supplies an empty value. Parsing does not mutate
`os.environ`. Missing explicit files are errors; absent optional managed files
contribute no values.

## Managed files

| File | Location and purpose |
| --- | --- |
| `apprc.defaults.env` | Package data for optional application defaults. |
| `.apprc-owner.json` | Ownership marker inside an initialized category root; category-specific, not secret content. |
| `apprc.user.env` | Enabled config root; saved user overrides. |
| `apprc.user.secret.env` | Enabled config root; private user secrets. |
| `apprc.toml` | Enabled config root; workspace registry. |
| `apprc.workspace.env` | Selected workspace root; workspace overrides. |
| `apprc.workspace.secret.env` | Workspace root; private workspace secrets. |

The workspace TOML schema is `schema_version = 1`, `selected_workspace`,
`[workspaces.NAME] root = ...`, and `[archived_workspaces.NAME]` archive/source
root records. AppRC does not interpret or upgrade old `storages` schema or
`apprc.storage.*` files. Historical files stay untouched unless their owner
separately handles them.

<br>

# Management and lifecycle

## ConfigManager

`MyRC.manage(options=None, *, environment=None)` returns a `ConfigManager`
without writing. It reads settings, inspects fields, performs user config setup,
secret status/repair, and creates edit/removal plans. `setup(*, adopt=False)`
initializes only enabled user config. Workspace registration belongs to
`WorkspaceManager`, not config setup.

| Operation | Behavior |
| --- | --- |
| `inspect()` | Field inspections, issues, and readiness without application state factories. |
| `writable_path(scope, secret=False)` | Path for `user` or selected `workspace` managed settings. |
| `plan_update(reference, raw_value, scope=...)` / `plan_removal(...)` | Validate a proposed write and capture the target file revision. |
| `preview_edit(plan)` | Show candidate settings without writing. |
| `apply_edit(plan)` | Apply only if the captured file revision still matches. |
| `setup(adopt=False)` | Initialize enabled user config and companions. |
| `secret_status(scope)` / `repair_secret_permissions(scope)` | Inspect or explicitly repair current secret permissions. |

A reference may be a dotted registered path, unambiguous field name, or complete
environment key. Write scopes are `user` and `workspace`. Edit plans reject a
changed file under the managed write lock. Ordinary config editing never adopts
an unrelated nonempty root.

## WorkspaceManager

`MyRC.workspaces(options=None, *, environment=None)` returns a `WorkspaceManager`
when Workspaces is declared. Workspace methods are explicitly named:
`registry_path()`, `registry()`, `inspect_registry()`, `register_workspace()`,
`select_workspace()`, `rename_workspace()`, `repoint_workspace()`,
`remove_workspace()`, `remove_archive_record()`, `move_workspace()`,
`archive_workspace()`, and `restore_workspace()`. Unregistering retains payloads.
`initialize_workspace(root)` initializes the explicit root's `apprc.workspace.env`
without writing config or registry files; it creates no secret companion.
Archive/restore validates traversal and secret exclusions and stages restore
before registration. New registered roots may not overlap AppRC-managed roots.
Direct-path mode does not offer registry mutations.

## Maintenance

Public records are frozen/slotted. `RemovalPlan(category, root, targets, revision,
warnings=())` carries an exact plan; `RemovalResult(removed, skipped=(),
warnings=())` reports application. `RemovalOperation(plan, apply)` pairs operations.
`AppDataOperations`, `CacheOperations`, and `StateOperations` expose named
callables; `MaintenanceHandlers(appdata=None, cache=None, state=None)` groups
them. Provider declarations for disabled components are errors.

`MyRC.maintain(options=None, *, environment=None, handlers=...)` returns a
`MaintenanceManager`. Its common operations are `info(kind)`,
`plan_purge(scopes: tuple[ResourceKind, ...])`, and
`apply_purge(plans: tuple[RemovalPlan, ...])`. Named provider-backed wrappers
are `backup_appdata(destination)` / `restore_appdata(source)`,
`plan_cache_prune()` / `apply_cache_prune(plans)`, corresponding cache clear,
state prune, and state reset pairs. Every plan returns a tuple of plans and every
apply returns a tuple of results. State operations address state and external
logs roots separately, deduplicating nested locations.

Purge validates every requested category before mutating any. Explicit disabled
scope is an error; `--all` means declared components only. A missing directory
has an empty plan and does not get initialized. Unknown resources, unsafe links,
nonempty unowned roots, mismatched markers, changed revisions, and out-of-root
targets refuse deletion. AppRC plans exact files and empty directories rather
than recursive instructions. Providers repeat freshness and lease checks under
their own coordination. A single-root parent and workspace payloads are never
purge targets. Multi-root apply is not atomic; partial results are reported.
Provider info values must be JSON-compatible values, not arbitrary objects.

Backup requires a new destination outside source appdata. Restore requires an
existing source and refuses nonempty appdata except its owner marker. Formats are
application-owned; AppRC does not convert data or export config/secrets.

## Provenance and lifecycle

`settings.provenance_of("timeout")` returns field origin information. Fields
include `field_name`, `source`, `origin`, `value`, redacted `display_value`,
`secret`, `env_key`, `path`, and packaged `resource`. File provenance records
its path. Current origin identifiers distinguish defaults, user dotenv,
workspace dotenv, explicit dotenv, process environment, constructor arguments,
assignments, and scoped overrides.

`reload_from(resolved, override_python_values=False)` validates before changing
the settings object. Python overrides remain authoritative by default. A
resolved snapshot's `AppPaths` does not change during settings refresh.
`reload()` and `bind_from_env()` use live process environment. `scoped()` makes
an isolated override; `export_environment()` explicitly changes process
environment and is not part of normal resolution.

<br>

# Commands and errors

## Terminal commands

`rc.cli.mount_app_cli(app, MyRC, *, handlers=..., maintenance_help_panel="Maintenance", ...)`
mounts the high-level route and returns `dict[str, typer.Typer]` for mounted
category subgroups. It owns the callback and rejects callback replacement.
Applications with their own callback use `CliRuntime.prepare()` and the
`CliRuntime.mount_app_groups()` method. Fixed groups are mounted only when their
declaration/capability exists. `build_config_typer_app` remains a config-only
advanced builder.

| Command | Availability and behavior |
| --- | --- |
| `paths [config\|appdata\|cache\|state\|logs] [--json] [--open]` | Always. No category lists all paths; category prints only its absolute path. Disabled category and invalid `--open` combinations exit 2. `--open` launches an existing directory and never creates it. |
| `doctor [--json]` | Always. Local/read-only config and declared-path diagnostics; no application factories or external services. JSON has `status` and `checks`, statuses `ok`, `warning`, or `error`. |
| `config init [--adopt]` | Config enabled; initialize user config and explicitly adopt nonempty unowned config when requested. |
| `config setup` | UserDotenv enabled; interactive setup and preference prompts. |
| `config show`, `set`, `edit`, config `doctor` | Typed schema available. Set scopes are `user` and `workspace`. |
| `config secrets ...` | Current config secret operations only; these do not migrate layouts or old registry formats. |
| `workspace add/list/select/rename/repoint/move/remove/archive/restore` | Registry mode (`registry=True`); registration and registry mutations require config enabled. |
| `workspace init PATH`, `workspace info PATH` | Direct mode (`registry=False`); initialize or inspect an explicit workspace path without a config/registry. |
| `<category> info [--json]`, `<category> init [--adopt]` | Enabled appdata/cache/state. `state init --logs` initializes logs only. |
| `appdata backup/restore` | Mounted only when corresponding handlers exist; restore confirms unless `--yes`. |
| `cache prune/clear`, `state prune/reset` | Mounted only when the corresponding provider operation exists; support dry-run/confirmation/JSON. |
| `purge --scope CATEGORY...` or `purge --all` | Always. Scope forms are mutually exclusive and required; preview/apply options described below. |

Root selectors include `--workspace`, `--layout native\|single-root`, and
`--app-root PATH`; they are captured before business-state setup is skipped.
Root `--env-file` and `--env-file-overrides-os-environ` preserve dotenv behavior.
No layout migration command exists.

For `paths --json` without a category, JSON is
`{layout, root, source, paths: {config, appdata, cache, state, logs}, exists: {config, appdata, cache, state, logs}}`. Disabled path and existence entries are `null`; a missing enabled directory has `exists=false`. Category JSON is `{category,path,exists}`. `--open` with JSON or without a category exits 2.

Purge JSON is `{plans:[{category,root,targets,revision,warnings}], results:[{category,root,removed,skipped,warnings}]}`. Preview returns `results: []`. It prints paths and revisions, never marker or secret contents. Confirmation is prompted once; JSON prompts go to stderr. Noninteractive apply needs `--yes`/`-y`. Exit 0 means successful preview/apply or empty `--all`; exit 1 means cancellation, partial result, or failure; exit 2 means invalid/unsafe preflight. There is no `appdata clean`, `appdata paths`, or `config purge` command.

## Errors and write guarantees

| Error | Meaning |
| --- | --- |
| Disabled path `ValueError` | Requested component was not declared. |
| Ownership/boundary refusal | Unsafe link, mismatched marker, overlap, unowned contents without adoption, or target outside its root. |
| Workspace selector error | Unknown registered name or named selector in direct mode; explicit invalid input is not replaced by a fallback. |
| Stale edit/maintenance plan | File or resource revision changed; inspect again and create a new plan. |
| Partial removal result | Some validated targets were skipped or failed; command exits nonzero and does not promise rollback. |

Managed writes use atomic same-directory replacement and locks. Plan/apply
operations compare revisions under their coordination boundary. Provider actions
must hold their own application locks/leases and revalidate freshness. Filesystem
operations across multiple roots are not transactions. Application callbacks,
settings factories, and SQLite operations can have application-specific effects;
local doctor and path inspection do not run those factories.
