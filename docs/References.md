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
  - [Distribution generation](#distribution-generation)
- [Value sources and files](#value-sources-and-files)
  - [Source precedence](#source-precedence)
  - [Managed files](#managed-files)
- [Management and lifecycle](#management-and-lifecycle)
  - [InstallationManager](#installationmanager)
  - [ConfigManager](#configmanager)
  - [WorkspaceManager](#workspacemanager)
  - [Maintenance](#maintenance)
  - [Provenance and lifecycle](#provenance-and-lifecycle)
- [Commands and errors](#commands-and-errors)
  - [Terminal commands](#terminal-commands)
  - [Launcher](#launcher)
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
| `rc.InstallationManager`, `rc.InstallationInspection`, `rc.InstallationRecord`, `rc.InstallationSnapshot` | Inspect and coordinate durable installation authority independently of resource capabilities. |
| `rc.installation_directory`, `rc.InstallationError` | Discover the fixed native address and report unusable installation authority. |
| `rc.schema`, `rc.provenance`, `rc.files` | Inspect declaration metadata, provenance, and dotenv parsing. |
| `rc.workspaces` | Read workspace records and registry helpers. |
| `rc.cli`, `rc.tui` | Typer adapters and Textual interfaces. |
| `apprc_gui.ConfigEditor` | Optional Gradio editor. |
| `apprc.scaffold` | `ConfigScaffoldRequest` and `scaffold_config_package()`. |
| `apprc.distribution` | Project metadata, verified source snapshots and explicit native setup builds; no custom dependency compiler. |
| `apprc.distribution.runtime` | Shared ordinary-Python installation/removal composition primitives. |

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
`environment`, `installation`, `declaration`, or `default`), and `config_dir`,
`appdata_dir`, `cache_dir`, `state_dir`, and `logs_dir`. Disabled resource
locations are `None`; disabled state also means disabled logs.
`ResolvedConfig.paths` always contains this snapshot, including declarations
with every resource disabled. Its required `installation: InstallationSnapshot`
contains `directory`, exact-byte `revision`, `generation_id` and diagnostics.
It is not a fifth resource capability or purge scope.

Fresh native mode uses platformdirs user locations and accesses only enabled
category properties. Linux config/cache/state/logs use their category properties;
appdata is the native app data container's `appdata/` child, beside
`installation/`. Windows and macOS append app-specific config, appdata and state
directories to their category bases; cache and logs use their native properties.
Disabled state means neither state nor log properties are accessed. When saved
placement wins, its recorded absolute paths are used instead of recomputing them
from the current environment.
Single-root mode maps enabled categories to `root/config`, `root/appdata`,
`root/cache`, and `root/state`; logs are `root/state/logs`.
`Layout.single_root` expands `~` and resolves relative roots against invocation
current working directory once. It never uses package location.

Path inspection creates no directories and repairs no ownership. Initialization
uses `.apprc-owner.json` with exactly `schema_version: 1`, `app_id`, and
`category`. Mutation refuses links/reparse points, overlapping managed roots,
mismatched markers, and nonempty unowned directories unless explicit adoption
is requested. Adoption claims contents; it does not move or delete them. Config
setup uses the same initializer, and `config setup --adopt` explicitly adopts an
existing nonempty config root. Ordinary edits never silently adopt. `ensure_path("state")`
does not initialize logs; `ensure_path("logs")` does. State maintenance returns
separate plans for distinct state/log roots and deduplicates nested roots.

No old location is scanned as a runtime fallback. A path declaration does not
enable UserDotenv, Workspaces, or a maintenance provider. Ordinary startup never
moves/deletes old files; explicit installation migration uses a reviewed exact
inventory and reports unsupported legacy data.

## Layout bootstrap

Controls are `<PREFIX>_LAYOUT` and `<PREFIX>_ROOT`; `<PREFIX>` is normalized
`app_id` unless `bootstrap_env_prefix` overrides it. Invocation `Layout` wins.
Otherwise AppRC selects the highest raw input layer containing either nonblank
control, then interprets that layer's pair as a unit. Root alone means
single-root; `native` plus root in that selected layer is an error; higher-layer
`native` ignores a lower-layer root. Saved installation placement, declaration
layout and then default native are fallback layers, in that order. Invocation
and raw-control overrides never rewrite saved placement.

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

## Distribution generation

Distribution authoring uses committed project source and the application's exact
`uv.lock`. The SDK delegates dependency installation to uv; it does not generate
runtime overrides, compile private dependency wheels or maintain a wheelhouse.

| API | Result / contract |
| --- | --- |
| `read_project_metadata(project_root)` | Packaging, import, app and console-command identities remain distinct. |
| `inspect_capabilities(apprc)` | Declared filesystem capabilities without resolving business settings. |
| `build_project_snapshot(spec, *, revision, destination, prepare=None)` | `PreparedProject(archive, source)` from one committed Git tree and optional authored preparation of its private staging copy. |
| `build_native_distribution(spec, project, *, uv, workspace, targets=..., extras=(), environment=None)` | Native setup artifacts and their checksum file. |
| `NativeFrontendBuilder.build(*, target, destination, runtime_archive, entrypoint)` | Compile the verified ordinary-module archive without executing the produced binary. |

Snapshot preparation retains the complete workspace, local member source,
`pyproject.toml`, `uv.lock` and build inputs. uv selects the installed package and
runtime extras; development/default groups are excluded from managed installs.
Local sources escaping the snapshot, unsafe archive members, missing metadata or
lockfiles, and output collisions fail before publication. Application-authored
preparation can build frontend assets into Python package data, but must remove
generated dependency directories and caches before archiving.

`ProjectSnapshot` records the archive SHA-256, lock SHA-256, full source commit
and relative project path. `RuntimeSelection` records the Python selector and
selected extras. `DistributionSpec` carries the project metadata, resource
declarations and typed installation hooks; it has no wheel/index/remote-main
source mode or injected runtime requirements.

Native outputs are confined to the repository's ignored `dist/`:

```text
dist/
├── <app-id>-setup-linux-x86_64
├── <app-id>-setup-windows-x86_64.exe
└── SHA256SUMS
```

Build inputs, source archives, compilation reports and caches stay under ignored
`.cache/apprc/`. Each setup embeds one shared SDK implementation, immutable app
binding and prebuilt project snapshot. It is also the installed stable native
command; installation copies it rather than compiling another launcher.
There are no standalone Python installer assets or shell/CMD/PowerShell wrappers.

The compiler pins PyApp 0.31.0 and uv 0.13.6. Management uses its own Python 3.14
bootstrap, independently of the selected application Python. Public SDK
management dependencies come from the matching SDK package metadata, not the
application graph. PyApp self-management commands are disabled; removal goes
through AppRC's ownership-aware lifecycle.

Supported compile targets are `x86_64-unknown-linux-gnu` and
`x86_64-pc-windows-msvc`. Windows cross-compilation/header validation is not
native Windows execution evidence; macOS builds remain deferred. See
[compiler prerequisites](Development.md#native-application-frontends).

### Runtime ownership

Managed release slots live below the fixed native installation directory:

```text
installation/
├── installation.json
├── <command>[.exe]
└── runtimes/
    └── <slot-id>/
        ├── project.zip
        ├── source/
        └── .venv/
```

The retained archive is the verified repair input; materialized source may
contain ordinary build intermediates. Environments are created at their final
paths with `uv sync --locked --no-default-groups --no-editable`, explicit Python,
package and extras selection, and the slot's absolute environment path.
An update activates its validated candidate through the existing record CAS.
Old slot IDs remain recorded until ownership-checked cleanup can obtain an
exclusive runtime lease. A live child retains its inherited lease even if its
native forwarding parent exits.

Editable registration instead records `EditableCheckout(project, environment)`.
It uses the checkout's existing `.venv`; AppRC neither resolves its dependencies
nor copies or owns the checkout/environment. Its global console entry is bound
to that environment, not the shell's activation. Restore a broken developer
environment with uv before invoking its maintenance commands.

### Application hooks and command dispatch

`InstallationHooks` contains optional importable `module:function` references:

| Hook | Callable |
| --- | --- |
| `initialize` | `(context: OperationContext) -> None`; idempotent application setup after SDK resource initialization. |
| `inventory` | `(inspection, categories, forget_retained) -> CleanupInventory`; exact resource ownership for removal. |
| `cleanup` | `(context: OperationContext) -> None`; application-owned cleanup under persisted authority. |
| `migrate` | `(plan: MigrationPlan, context: OperationContext) -> None`; application-specific migration in an application runtime. |

Pass the same declaration to `DistributionSpec.hooks` and CLI
`installation_hooks`. This replaces `installation_inventory`; no alias remains.
Runtime hooks must be packaged with the application, not merely present in an
author-only `<app>_distr` package.

The native command handles `app doctor`, `paths`, `repair`, `uninstall` and
`migrate` through the same AppRC maintenance implementation as the app CLI.
Normal application/config/workspace commands, application-owned data/cache/state
operations and `launch` run in the absolute recorded runtime. Doctor always
reports independent installation health and may add actual application checks;
unavailable checks are explicit. Unavailable application hooks block dependent
cleanup/migration rather than silently succeeding.

`app install -e` is available for installation-enabled application CLIs.
`--command-directory` chooses an existing PATH directory without editing shell
profiles; `--yes` confirms the reviewed operation and `--skip-setup` skips only
the optional post-Ready configuration offer. Native setup installs its embedded
release; updates use newer setup, not `--main`, `--version` or wheel/index input.

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
| `installation.json` | Sole authority in the fixed native `installation/` directory; no secrets, unrelated to `.apprc-owner.json`. |
| `<command>` / `<command>.exe` | Owned stable native manager inside the installation directory; global integration points here. |
| `runtimes/<slot-id>/project.zip` | Verified committed project retained for managed repair; adjacent `source/` and `.venv/` belong to that slot. |
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

## InstallationManager

`MyRC.installation(*, environment=None)` captures installation discovery without
resolving business settings or writing files. The fixed native authority remains:

| OS | Installation directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%/<app-id>/installation` |
| macOS | `~/Library/Application Support/<app-id>/installation` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/<app-id>/installation` |

This address is independent of optional resource capabilities, native/single-root
resource layout, checkout and CWD. A changed OS profile/discovery base requires
explicit relocation; AppRC does not scan other users' locations for receipts.

`inspect()` returns installation status, address, revision and structured
diagnostics without creating authority. Statuses remain `missing`, `invalid`,
`provisional`, `ready`, `incomplete` and `removed-retained`. Unmanaged pip
installations do not require a record. Invalid authority never authorizes a
silent fallback to another resource location.

Schema `3` is strict: wrong types, duplicate/unknown fields, malformed identities
or digests and invalid paths are rejected. Schema-2 managed installations must
be retired with their matching old tools before reinstallation; no converter or
compatibility controller is provided. Resource ownership markers and workspace
TOML keep their separate schemas. Record revision remains the SHA-256 of its
exact encoded bytes, not another persisted counter.

| Record field | Meaning |
| --- | --- |
| `identity`, `command_name`, `generation_id`, `support_version` | Application/distribution identity, primary command, installation identity and SDK support version. |
| `placement` | Committed absolute resource locations, capabilities and retained earlier locations. |
| `active_runtime` | Validated managed slot or non-owned editable checkout; remains selected while a replacement is prepared. |
| `retiring_runtime_ids` | Exact owned old slots awaiting safe collection; never an instruction to sweep arbitrary directories. |
| `operation` | Exact pending target, checkpoints, authenticated output-publication intent, retry preconditions and failure diagnostic. |
| `owned_outputs` | Digest-owned support, global commands, shortcuts and registration—not shared uv/Python or an editable environment. |
| `migration` | Explicit resource-placement migration state and inventory. |

`generation_id` identifies the installation; `slot_id` identifies one managed
runtime. Ready accepts either an observed managed slot or a validated editable
checkout. Removal with retained resources clears the active target and records
`removed-retained`; it does not claim the program still exists.

Lifecycle operations retain physical namespace locks, exact-revision CAS,
operation-context checks and failure checkpoints. Candidate initialization
requires its matching operation context. Ordinary access uses the committed
active target during replacement; uninstall and resource migration retain their
quiescence boundaries and stale captured writers remain rejected.

Resource migration keeps its inventory/checkpoint engine in core.
`migrate(..., migration_hook=...)` and
`resume_migration(..., migration_hook=...)` can receive an explicit
`(MigrationPlan, OperationContext) -> None` callback. The shared CLI supplies
the existing application-runtime bridge when a recorded provider is required;
core does not import distribution execution or accept a native executable path.
The hook runs only after pending authority is durable, and its completion is
checkpointed before resource moves. Missing required code blocks those moves.

`InstallationManager.initialize(context=...)` is the shared declared-resource
initialization path for managed and editable registration. Application code runs
only in its recorded runtime. The independent manager can diagnose, repair or
remove a broken managed program without importing it, but cannot pretend that
unavailable application-specific validators or cleanup hooks ran.

Program-only removal preserves user resources by default. Complete removal
requires explicit choices and exact provider inventories; unknown files,
changed ownership or unavailable required code block unsafe deletion. Temporary
native finalization waits for its initiating process before removing owned
program files. No saved Python/CMD/PowerShell management copies are required.

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
| `plan_secret_migration(scope)` | Capture both file revisions and a value-preserving move to the private companion. |
| `apply_secret_migration(plan)` | Recheck both revisions under the managed lock, then write the companion before removing ordinary-file assignments. |

A reference may be a dotted registered path, unambiguous field name, or complete
environment key. Write scopes are `user` and `workspace`. Edit plans reject a
changed file under the managed write lock. Ordinary config editing never adopts
an unrelated nonempty root.

Field inspections expose `reason` as `None`, `"missing"`, or `"invalid"`.
`issue` is display text; consumers must use `reason`, not parse its wording,
when deciding whether to prompt for a missing value.

Secret-file status likewise separates display text from `reason`: `None`,
`"parent_missing"`, `"parent_not_directory"`, `"parent_not_private"`,
`"secret_not_file"`, or `"secret_not_private"`. Use these values for repair
eligibility and recovery actions; an available secret location has no reason.

> [!WARNING]
> Secret migration replaces two files separately, not as one crash-atomic
> transaction. An interruption after writing the private companion can leave
> the original ordinary-file assignments in place. The private values remain
> available, but migration is not finished. Reapplying the original plan raises
> `StaleEditError` because its companion revision has changed. Create and review
> a fresh plan with `plan_secret_migration(scope)`, then pass that plan to
> `apply_secret_migration()` to remove the remaining ordinary-file copies.

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

Purge is a Python service operation, not an application CLI command.
`plan_purge(scopes)` validates every requested category before mutating any;
an explicitly disabled scope is an error. Pass the declared categories explicitly
to plan all enabled resources. A missing directory has an empty plan and does not
get initialized. Unknown resources, unsafe links, nonempty unowned roots,
mismatched markers, changed revisions, and out-of-root targets refuse deletion.
AppRC plans exact files and empty directories rather than recursive instructions.
Providers repeat freshness and lease checks under their own coordination. A
single-root parent and workspace payloads are never purge targets. Multi-root
apply is not atomic; partial results are reported. Provider info values must be
JSON-compatible values, not arbitrary objects.

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

Provenance updates share one per-instance origin map for Python-only and
environment-backed fields. `apprc.provenance.set_field_origin(instance,
field_name, origin)` updates origin metadata on an existing instance; it does
not assign the field's value. For a pure mapping copy, use ordinary Python such
as `{**origins, field_name: origin}` rather than the removed `with_field_origin`
utility.

<br>

# Commands and errors

## Terminal commands

`rc.cli.mount_app_cli(app, MyRC, *, ...)` installs the standard root callback and
returns `dict[str, typer.Typer]` for the groups actually mounted. It rejects an
existing host callback. Applications that own their callback instead construct
`rc.cli.CliRuntime(...)`, call `runtime.prepare(ctx, options)`, and register groups
with `runtime.mount_app_groups(app, ...)`. There is no module-level
`mount_app_groups()` function. `build_config_typer_app()` remains the advanced
config-only builder.

### Composition arguments

All arguments after `app, apprc` in `mount_app_cli()` are keyword-only. The
following existing controls remain supported:

| Keyword | Default | Meaning |
| --- | --- | --- |
| `config_group_name` | `"config"` | Name of the enabled config group. |
| `state_type` | `DefaultConfigCliState` | Type of application-owned runtime state; a custom type requires a factory. |
| `state_factory` | `None` | Build host state after ordinary AppRC resolution; the high-level factory receives `CliRuntimeContext`. |
| `args_provider` | `None` | Supply invocation tokens for embedded use; otherwise use the current invocation. |
| `runtime_policy` | `None` | `ConfigRuntimePolicy` or `CliRuntimePolicy` for additional runtime-independent host command paths. |
| `workspace_required` | `False` | Require a workspace for ordinary business execution; requires a Workspaces declaration. |
| `handlers` | `MaintenanceHandlers()` | Explicit supported appdata, cache, and state operations. |
| `maintenance_help_panel` | `"AppRC: Commands"` | Help metadata panel for injected root entries. |
| `installation_hooks` | `InstallationHooks()` | Importable application lifecycle providers; see the hook contract above. |
| `runtime_payload` | `None` | Serialize application state for `config show`. |
| `active_workspace_root_with_context` | `None` | Selector-aware active-workspace resolver for config commands. |
| `initial_workspace_with_context` | `None` | Selector-aware initial workspace resolver for the config editor. |
| `editor_app_cls` | `None` | Custom Textual config editor class. |
| `help` | `None` | Config-group help override. |
| `setup_message` | `None` | Config setup message override. |
| `runtime_error_param_hint` | `"CONFIG"` | Parameter hint when converting runtime/config errors. |
| `setup_logging` | `None` | Host logging setup callable, invoked before business resolution. |
| `logger` | `None` | Resolution logger. |

The composition extension keywords have these exact types and defaults:

| Keyword | Type/default | Meaning |
| --- | --- | --- |
| `maintenance_group_name` | `str = "app"` | Maintenance command path and returned mapping prefix. |
| `installation_management` | `bool = False` | Enable editable installation plus `repair`, `uninstall` and `migrate`; never inferred from an existing record at mount time. |
| `installer_entrypoint` | `Callable[[Sequence[str]], int] \| None = None` | Optional authored delegate for noneditable `app install`; otherwise direct the user to native setup. A noncallable is rejected. |
| `host_diagnostics` | `Callable[[], Mapping[str, object]] \| None = None` | Local, read-only host metadata, evaluated only by verbose doctor. |
| `resource_diagnostics` | `Mapping[Literal["appdata", "cache", "state"], Callable[[Path], Mapping[str, object]]] \| None = None` | Explicit local, read-only resource details on safe existing roots, only in verbose doctor. |
| `resource_group_extensions` | `Mapping[Literal["appdata", "cache", "state"], Callable[[typer.Typer], None]] \| None = None` | Register host commands on detached declared resource groups before empty-group filtering. |
| `launcher_spec` | `LauncherSpec \| None = None` | Enable root `launch` using AppRC's existing Textual launcher. |
| `launcher_handlers` | `Mapping[str, LauncherHandler] \| None = None` | Action handlers forwarded to the launcher; invalid without a spec. |

`CliRuntime` accepts the runtime/config controls above on its constructor,
including `maintenance_group_name`, but not the group-composition inputs
`handlers`, `maintenance_help_panel`, `installation_hooks`,
`installation_management`, `installer_entrypoint`, `host_diagnostics`,
`resource_diagnostics`, `resource_group_extensions`, `launcher_spec`, or
`launcher_handlers`. Pass those to `runtime.mount_app_groups(app, *, ...)`;
that method reads `maintenance_group_name` and `config_group_name` from the
runtime rather than taking them again. Its `handlers`, help-panel and hook
defaults match the high-level mount, as do all extension defaults above.
The low-level `state_factory` receives `(CliRuntimeContext, options)`, preserving
host-owned option types; selector-aware workspace callbacks receive host state
and `ConfigSelectorContext`.

Before modifying the host tree or installing a generated callback, composition
preflights every enabled root name, including conflicts between configured
names. It rejects a colliding host command/group without partially mounting.
The reserved names are the configured maintenance name, enabled config name,
conditional `workspace`, and `launch` only with a spec. Removed names such as
root `paths` are not reserved. Resource registrations for undeclared categories
are errors. A resource group appears only if the category is declared and at
least one built-in or extension command is registered.

Returned mapping keys are actual mounted paths: `config`, `workspace`, `app`,
`app.data`, `app.cache`, and `app.state`, omitting unavailable entries. Custom
config/maintenance names replace the corresponding names and prefixes. There
are no flat `cache` or `appdata` compatibility keys. Register host resource
commands through `resource_group_extensions` so they participate in availability
filtering; returned mounted groups remain directly accessible.

### Root help and runtime options

Opt in with `typer.Typer(cls=rc.cli.AppRCRootGroup, ...)` for the ordered,
nonempty panels `Options`, `Commands`, `AppRC: Runtime Options`, and
`AppRC: Commands`. Host options/commands remain in the first two panels;
AppRC options and injected entries use the latter two. Applications that do not
opt in retain ordinary Typer help. Nested help, parsing, completion, no-color
output, and eager help exits retain normal Typer behavior. Root help never
expands nested commands into extra root rows.

The maintenance row reads `Inspect and maintain the application (<available names>).`
from its actual immediate commands in registration order: `doctor`, `paths`,
`install`, `repair`, `uninstall`, `migrate`, `data`, `cache`, `state`, filtering
unavailable entries. Registered host extensions determine resource availability.
The remaining injected descriptions are:

| Entry | Root description |
| --- | --- |
| `launch` | Open the interactive AppRC application launcher. |
| `config` | Inspect resolved settings, update saved configuration, or open the interactive configuration editor. |
| Registry `workspace` | Register, select, move, archive, or restore workspaces. |
| Direct `workspace` | Inspect a workspace path or initialize it explicitly. |

All seven public option annotations are accepted by
`CliRuntimeOptions.from_typer()` and preserved by
`cli_runtime_options_to_args()`:

| Annotation | Root option | Behavior |
| --- | --- | --- |
| `EnvFilesOption` | `--env-file PATH` | Repeatable explicit files in order; later files win. Process environment wins unless `-o` is supplied. |
| `EnvFileOverridesOption` | `--env-file-overrides-os-environ`, `-o` | Explicit files override captured process environment. |
| `SkipDotenvLayersOption` | `--skip-dotenv-layers`, `-s` | Exclude managed dotenv layers, retaining explicit files and process environment. |
| `WorkspaceOption` | `--workspace VALUE` | Select a registered workspace name or a direct path according to the declaration. |
| `LayoutOption` | `--layout native\|single-root` | Override the layout for this invocation only. |
| `AppRootOption` | `--app-root PATH` | Supply this invocation's single-root location; never rewrite saved placement. |
| `LogLevelOption` | `--log-level LEVEL` | Configure logging before business configuration resolution. |

Persist layout choices through the authored installer's `--layout native` or
`--layout single-root --root PATH`; resource migration is a separate explicit
operation. Forward embedded calls with `runtime.run_forwarded(...)`, which uses
the forwarded token stream rather than unrelated process arguments. Structural
help at every depth, including options before a subcommand, avoids managed-path
and business-setting resolution; option values and tokens after `--` are not
misclassified as commands.

`CliRuntime.prepare()` returns a session whose `apprc_context` is either
`CliRuntimeContext` or `InstallationCommandContext`. The recovery context has
captured selectors/environment, installation inspection/manager and optional
`path_error`, not fabricated paths or business settings. Maintenance and workspace
commands never build host business state. Saved lifecycle actions, explicit
install and configured root launch prepare recovery context before strict
path/business resolution. Doctor/paths retain safe inspection context when path
resolution fails. `ctx.obj` remains application-owned; session metadata itself
does not become nullable. Advanced adapters can use
`installation_command_context_from(ctx)` and
`prepare_installation_command_context(...)`.

For a native manager, successful path resolution retains the captured installation
authority in `CliRuntimeContext.installation_context`.
`installation_command_context_from(ctx)` retrieves either form, so doctor can
probe the active runtime even when application paths resolve successfully.
Ordinary application invocations leave `installation_context` as `None`.

### Command tree

Paths below use default group names. Only host commands, enabled `config`,
conditional `workspace`, `app`, and optional `launch` appear at the root.

| Command | Availability and behavior |
| --- | --- |
| `app doctor [--verbose] [--json]` | Always. Aggregate local/read-only installation, path, ownership, boundary and config diagnostics; no host business factories or remote services. JSON contract below. |
| `app paths [config\|appdata\|cache\|state\|logs] [--json] [--open]` | Always. Without a category, list all paths; a category prints its absolute path. Disabled category and invalid `--open` combinations exit 2. Open only an existing directory; never create it. Original authority/path failures exit nonzero without fallback locations. |
| `app install [-e/--editable] [ARGS]...` | Enabled by installation management or an explicit installer delegate. Editable registration uses the invocation's actual checkout `.venv`; it never syncs/copies an environment. Other arguments go to the authored delegate, if present; otherwise explain how to run native setup. `--help` remains local. |
| `app repair` | `installation_management=True`. Rebuild the recorded managed project through authenticated native support without selecting newer source or changing placement. Editable environments receive `uv sync --locked` guidance instead. |
| `app uninstall [--dry-run] [--complete] [--category KIND] [--forget-retained] [--yes/-y]` | `installation_management=True`. Shared saved removal procedure; repeat categories for config/appdata/cache/state. Program-only is the default and retains resources. Complete removal requires exact preview/consent. |
| `app migrate [--dry-run] [--yes/-y]` | `installation_management=True`. Preview/apply exact resource migration, or resume its saved pending inventory/revision, with confirmation and quiescence checks. Unrecognized data needs application-owned inventory; recovery never rescans it silently. |
| `app data backup/restore` | Declared appdata and corresponding provider operations. Restore confirms unless `--yes`; data means AppRC appdata, never workspace/project payloads. |
| `app cache prune/clear`, `app state prune/reset` | Declared category and supported provider operations; preserve dry-run, confirmation and JSON controls. Host resource extensions may provide application-specific commands. |
| `config setup [--adopt] [--yes/-y]` | Config initialization or user-dotenv setup supported. Config-only declarations get idempotent initialization; user-dotenv declarations retain guided/noninteractive setup. Explicit adoption is required for nonempty unowned config. |
| `config show`, `config set`, `config edit` | Typed schema available. Set scopes are `user` and `workspace`. |
| `config secrets ...` | Supported config secret operations; no layout/old-registry migration. |
| `workspace add/list/select/rename/repoint/move/remove/archive/restore` | Registry mode (`registry=True`); registry mutations require config enabled. |
| `workspace init PATH`, `workspace info PATH` | Direct mode (`registry=False`); initialize/inspect an explicit workspace path without config/registry. |
| `launch` | Only with `launcher_spec`. Open one Textual event loop without business settings; `launch --help` never starts it. |

There is no generic resource `init`/`info`, CLI purge, `installation` group,
config `init`/`paths`/`doctor`, or root AppRC `paths`/`doctor` alias. Python
`ensure_path()`, maintenance `info()`/`plan_purge()`/`apply_purge()` and public
config diagnostic/output helpers retain their service semantics. The separate
developer CLI `apprc scaffold config` and authored distribution entries are
unchanged.

### Saved removal inventory

Declare application-owned inventory through
`InstallationHooks(inventory="package.module:function")`, not a live
`installation_inventory` callback. The shared implementation imports the
provider only inside the recorded application runtime. Native maintenance
does not install or import application dependencies.

The inventory provider receives the captured installation, normalized resource
categories and `forget_retained` choice. Return only exact owned resource
entries; selected complete removal requires the provider before any purge.
Program-only removal, help and independent diagnosis do not require it.
Pending uninstall reuses its accepted persisted inventory rather than silently
rescanning after consent.

Providers can compose
`apprc.distribution.runtime.default_cleanup_inventory(inspection, categories=categories, forget_retained=forget_retained)`.
The shared strict codec, ownership/revision validation and operation checkpoints
remain authoritative. A missing or failing provider prevents dependent cleanup;
it does not justify treating a whole application directory as owned payload.

### Doctor and paths JSON

`app doctor --json` always returns this envelope:

| Key | Contract |
| --- | --- |
| `status` | Ordinary `ok`, `warning`, or `error`; preserve unusable installation statuses `invalid`, `provisional`, or `incomplete`. |
| `checks` | Always an array of `{name, status, message}` records. Include installation/path ownership, boundary, config readiness/validation and explicit diagnostic-callback failures. Preserve real errors and recovery messages. |
| `installation` | Always `{status, app_id, directory, revision, record, diagnostics}`. Each diagnostic has `code`, `message`, and `recovery`. Retain raw saved authority, including broken records. |
| `details` | Present only with `--verbose`; exactly the detail categories `paths`, `configuration`, `resources`, and `host`. |

Verbose `details.paths` is the existing all-path payload or `null` without safe
paths. `details.configuration` is the existing config doctor payload or `null`
when unavailable, using captured config selectors rather than a fresh default
resolution. `details.resources` is keyed by declared `appdata`, `cache`, and
`state`; each entry reports `root`, `exists`, `ownership`, available operation
names, and optional `provider`. Unknown locations/ownership are `null`, never
invented paths. `details.host` is the explicit host callback mapping or `{}`.

Only explicitly registered `resource_diagnostics` callbacks run, and only for
existing roots that passed link/ownership checks. Doctor never implicitly invokes
`MaintenanceHandlers.info`, acquires a resource by writing, initializes missing
directories, or queries remote providers. Expected `OSError`/`ValueError` callback
failures become named error checks; programming exceptions are not blanket-caught.
Host metadata remains available even if placement is broken.

An error check or unusable installation status exits 1; warnings alone exit 0.
`--json` changes representation, not health or status. Verbose callbacks can reveal
additional failures, which also exit 1. If paths cannot resolve, append the original
resolution error without changing otherwise valid saved authority. An explicit
invocation layout does not erase captured installation errors or rewrite the
record.

`app paths --json` without a category preserves
`{layout, root, source, paths: {config, appdata, cache, state, logs}, exists: {config, appdata, cache, state, logs}}`.
Disabled entries are `null`; missing enabled directories have `exists=false`.
Category JSON remains `{category,path,exists}`. `--open` with JSON or without a
category exits 2. Resolution failure is a controlled nonzero error, not a
successful invented payload; use doctor for the recovery report.

### Breaking CLI and JSON migration

No compatibility aliases survive. Existing scripts must change as follows:

| Previous CLI | Current interface |
| --- | --- |
| Root `paths` | `app paths` |
| Root/config/installation doctor or host diagnose | `app doctor` |
| `installation show`, resource `info` | `app doctor --verbose` |
| `installation repair/uninstall/migrate` | `app repair/uninstall/migrate` |
| `config init` | `config setup` |
| `appdata backup/restore` | `app data backup/restore` |
| Root cache/state operations | `app cache ...`, `app state ...` |
| Example root `launcher` | Optional root `launch` |
| CLI purge or generic resource init | No CLI replacement; use explicit Python service operations. |

Doctor's envelope deliberately replaces previous diagnostic JSON shapes. Consumers
must read `checks` and `installation` from the new envelope, config diagnostics
from verbose `details.configuration`, local provider metadata from
`details.resources.<kind>.provider`, and host diagnose metadata from `details.host`.
Successful paths and resource/lifecycle operation JSON contracts are unchanged.

## Launcher

Optional terminal exports live under `apprc.interfaces.tui`:
`LauncherSpec`, `LauncherAction` and
`run_launcher(apprc, *, spec, options=None, environment=None, handlers=None, log_level=None)`.
`LauncherSpec(actions=(), title="Application launcher")` owns one application's
home screen. Each `LauncherAction(id, label, argv, interactive=True, group="main")`
has an identifier, visible label and argv factory accepting captured
`LauncherContext` plus a dry-run flag. `group` is `"main"` or `"project"`.
Commands use argument vectors, never shell strings.
The optional `log_level` is captured on `LauncherContext.log_level` (default
`None`) so application-owned action factories can forward the invocation's
logging selector with the other runtime options. Root `launch` supplies it
without resolving business configuration.

Supply `launcher_spec` to either [composition entry point](#composition-arguments)
to register root `launch`. It invokes this existing launcher lazily, forwarding
the captured environment and `ResolveOptions` fields `workspace`, `layout`,
ordered `env_files`, `env_file_overrides_os_environ`, and `load_dotenv_layers`.
Optional `launcher_handlers` maps action IDs to
`Callable[[LauncherContext, bool], Awaitable[object] | object]`. An empty
`LauncherSpec(actions=())` still exposes supported built-in management controls.
`launch --help` does not create the UI. This is not the application's foreground
entry point or a separate native launcher executable.

Launcher captures installation diagnostics and optional valid paths without
building business settings. Capability-driven management stays available when
settings are missing; invalid authority disables unsafe path actions instead of
manufacturing fallback paths. The reusable `ConfigEditorScreen` shares the
launcher's Textual event loop; `ConfigEditorApp` remains the standalone adapter.
Long work uses workers, interactive children use terminal suspend/resume, and
only launcher-owned foreground children are stopped/awaited.

Uninstall hands control to independent saved support and exits the actual
installed entry process; closing a Textual screen/App alone is not sufficient.
Ordinary launch does not run `uv sync`, create an environment or start business
services merely to display management.

## Errors and write guarantees

| Error | Meaning |
| --- | --- |
| Disabled path `ValueError` | Requested component was not declared. |
| `InstallationError` | Invalid/incomplete authority, stale managed generation, unreconciled capabilities or unsafe lifecycle transition; inspect/repair rather than selecting fallback data. |
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
Installation mutation additionally serializes on its lifecycle lock and validates
the captured generation. Existing stable sibling resource/workspace locks remain
the coordination boundary for common explicit roots; they are not purge targets.
Only a validated explicit `OperationContext` authorizes manager writes within a
pending install/repair/migration; ordinary installed consumers must restart after
generation changes.
