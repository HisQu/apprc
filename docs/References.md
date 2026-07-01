<!-- ======================================================== -->

<br>

## Table Of Contents
<!-- ======================================================== -->

1. [References](#1-references)
2. [Runtime Config Reference](#2-runtime-config-reference)
   1. [Public Interfaces](#public-interfaces)
   2. [Capability Constructors](#capability-constructors)
   3. [Configuration Files](#configuration-files)
   4. [Environment Variables](#environment-variables)
   5. [Runtime Precedence](#runtime-precedence)
   6. [Storage Selector Precedence](#storage-selector-precedence)
   7. [Generated CLI Commands](#generated-cli-commands)
   8. [Doctor Statuses](#doctor-statuses)
   9. [Dotenv Helper APIs](#dotenv-helper-apis)
   10. [Optional Logging APIs](#optional-logging-apis)
3. [Repository Reference](#3-repository-reference)
   1. [Project Paths](#project-paths)
   2. [Dependency Surfaces](#dependency-surfaces)
   3. [Documentation Assets](#documentation-assets)

<br>

# 1. References

Use this file when you need an exact import, command, filename, environment
variable, or status. Use [How-To User Guides](How-To-User-Guides.md) for
procedure and [Explanations](Explanations.md) for concepts.

<br>

# 2. Runtime Config Reference

<!-- ======================================================== -->

<br>

## Public Interfaces
<!-- ======================================================== -->

Top-level `apprc` imports for normal integrations:

| Import | Purpose |
|---|---|
| `AppConfigKit` | High-level app config facade. |
| `AppConfigSpec` | Lower-level application config contract. |
| `EnvConfig` | Base class for typed env-backed config sections. |
| `BaseConfig` | Base class for Python config objects with provenance and scoped overrides. |
| `env_owner` | Decorator that declares one config owner. |
| `env_field` | Dataclass field helper for one env-backed setting. |
| `config_owner_for` | Return the derived `ConfigOwner` for an `EnvConfig` class. |
| `ConfigOwner` | Normalized owner metadata. |
| `ConfigField` | Normalized field metadata. |
| `ConfigProvenance` | Provenance record for an effective config value. |
| `EnvBootstrapResult` | Files and storage selected during bootstrap. |
| `ConfigDoctorStatus` | Readiness status enum used by `config doctor`. |

Root `apprc` names for CLI integrations:

| Import | Purpose |
|---|---|
| `mount_config_cli` | Mount standard AppRC host-level options, default help-safe skip policy, and the generated `config` group on a Typer app. |
| `CliBootstrapOptions` | Parsed standard AppRC host-level option values. |
| `CliBootstrapContext` | Per-CLI-run AppRC bootstrap metadata stored on Typer context metadata. |
| `MountConfigCliStateFactory` | Callable type for `mount_config_cli(...)` state factories created after runtime bootstrap. |
| `CliArgvProvider` | Callable type for explicit command tokens used by mount skip-policy tests and forwarding CLIs. |
| `ConfigCliBridge` | Composable Typer bridge for apps that own their host callback and app-specific options. |
| `ConfigCliSession` | Result returned by `ConfigCliBridge.prepare(...)`, including AppRC context and optional app state. |
| `ConfigCliStateFactory` | Callable type for bridge state factories that receive AppRC context plus the app option object. |
| `BootstraplessCommand` | Declaration for host command actions that can run without app runtime state. |
| `HostCliBootstrapPolicy` | Skip policy for generated config commands plus app-declared bootstrapless host commands. |
| `DefaultConfigCliState` | Minimal config state for apps that do not need custom host state. |
| `prepare_typer_context` | Store AppRC bootstrap metadata from a custom Typer host callback. |
| `apprc_context_from` | Read AppRC bootstrap metadata from a Typer command. |
| `apprc_options_to_args` | Convert parsed AppRC options back into CLI tokens for lazy forwarding. |
| `ConfigBootstrapPolicy` | Config-command bootstrap skip policy with customizable bootstrapless actions. |
| `bootstrap_cli_env` | Typer-friendly wrapper around `AppConfigKit.bootstrap(...)`. |
| `config_request_skips_runtime_bootstrap` | Detect generated config commands that can run before runtime setup. |
| `ConfigSelectorContext` | Context passed to selector-aware config CLI hooks. |

Advanced storage and dotenv helpers are also exported from the root facade.
Prefer the root facade for stable application imports unless a lower-level
module is explicitly needed.

<br>

<!-- ======================================================== -->

<br>

## Capability Constructors
<!-- ======================================================== -->

| Constructor | Storage layer | App-wide layer | Named-storage index | Setup behavior |
|---|---|---|---|---|
| `AppConfigKit.env_only(...)` | disabled | optional | disabled | Prints env guidance; writes nothing. |
| `AppConfigKit.storage_only(...)` | required | optional | optional | Creates selected storage root and `.env.apprc-storage`. |
| `AppConfigKit.app_wide_config(...)` | disabled | default | disabled | Creates `.env.apprc-app`. |
| `AppConfigKit.app_wide_storage(...)` | required | default | optional | Creates `.env.apprc-app` and selected storage `.env.apprc-storage`. |

Constructor arguments:

| Argument | Meaning |
|---|---|
| `app_name` | Lowercase app name used for config home and derived env vars. |
| `display_name` | Human-readable app name for CLI output. |
| `config_package` | Package containing `.env.shared`. |
| `envs` | Tuple of `EnvConfig` classes decorated with `@env_owner(...)`. |
| `storage_env_key` | Optional explicit active-storage selector env key. Storage-capable constructors only. |
| `command_name` | Optional executable/app command name shown in generated CLI copy. |
| `index_filename` | Optional named-storage index basename. |
| `shared_env_filename` | Packaged shared dotenv filename. Default: `.env.shared`. |
| `app_wide_env_filename` | App-wide dotenv filename. Default: `.env.apprc-app`. |
| `storage_env_filename` | Storage dotenv filename. Default: `.env.apprc-storage`. |

Filename arguments accept basenames only, not paths.

<br>

<!-- ======================================================== -->

<br>

## Configuration Files
<!-- ======================================================== -->

| File | Default Location | Owner |
|---|---|---|
| `.env.shared` | Host app config package | Packaged defaults. |
| `.env.apprc-app` | Platform config home for the app | Per-user app-wide overrides. |
| `.env.apprc-storage` | Selected storage root | Storage-local overrides. |
| `<app>.apprc.toml` | Platform config home for the app | Optional named-storage index. |

Platform config home is resolved by `platformdirs.user_config_path` with
`appauthor=False`.

Legacy files `.env.global` and old storage-local dotenv names are ignored by
current AppRC. `config doctor` warns when legacy files are present.

<br>

<!-- ======================================================== -->

<br>

## Environment Variables
<!-- ======================================================== -->

Derived variables use the normalized `app_name` unless overridden.

| Variable | Purpose |
|---|---|
| `<APP>_STORAGE` | Active storage selector for storage-capable apps. |
| `<APP>_APPRC_TOML` | Optional relocation for the named-storage index. |
| Owner-prefixed field keys | Concrete runtime settings, for example `MYAPP_PROFILE`. |

Example for `app_name="myapp"`:

| Variable | Meaning |
|---|---|
| `MYAPP_STORAGE` | Active storage path or registered storage name. |
| `MYAPP_APPRC_TOML` | Optional path to `myapp.apprc.toml`. |
| `MYAPP_PROFILE` | A field declared by an owner with `env_prefix="MYAPP_"`. |

<br>

<!-- ======================================================== -->

<br>

## Runtime Precedence
<!-- ======================================================== -->

When dotenv layers are loaded, later rows win:

| Order | Source |
|---|---|
| 1 | Packaged `.env.shared`. |
| 2 | App-wide `.env.apprc-app`, when allowed and present. |
| 3 | Selected storage `.env.apprc-storage`, when storage is selected and present. |
| 4 | Explicit `--env-file` values. Later explicit files override earlier explicit files. |
| 5 | Existing `os.environ`. |

With `--env-file-overrides-os-environ`, explicit env files move after
`os.environ` and win over shell exports.

<br>

<!-- ======================================================== -->

<br>

## Storage Selector Precedence
<!-- ======================================================== -->

Storage selector sources:

| Order | Source |
|---|---|
| 1 | Host-level `--storage`. |
| 2 | Shell env, for example `MYAPP_STORAGE`. |
| 3 | Explicit env files, respecting `--env-file-overrides-os-environ`. |
| 4 | App-wide `.env.apprc-app`, when active. |
| 5 | Packaged `.env.shared`. |

Selector forms:

| Form | Behavior |
|---|---|
| Absolute path | Use as storage root. |
| Relative path with separator, `.` or `..` | Use as storage root. |
| Registered name | Resolve through the named-storage index. |
| Bare unknown name with no index | Treat as a path selector. |
| Bare unknown name with an index containing storages | Error; use `./name` for a relative path. |

<br>

<!-- ======================================================== -->

<br>

## Generated CLI Commands
<!-- ======================================================== -->

Commands are shown with `myapp` as the host app command.

| Command | Purpose | Writes |
|---|---|---|
| `myapp config paths` | Show paths, capabilities, selectors, and index state. | no |
| `myapp config doctor` | Check readiness and suggest fixes. | no |
| `myapp config show` | Show resolved runtime payload. | no |
| `myapp config setup` | Initialize files for the selected capability constructor. | yes |
| `myapp config set KEY VALUE` | Write one app-wide or storage dotenv value. | yes |
| `myapp config edit` | Open the Textual editor. Opening is zero-write; saving writes. | save only |
| `myapp config app init` | Create the app-wide dotenv file. | yes |
| `myapp config storage add NAME PATH` | Register a named storage and ensure its storage dotenv. | yes |
| `myapp config storage list` | List registered storages. | no |
| `myapp config storage remove NAME` | Remove a storage entry from the index. | yes |

`--json` is available on `paths`, `doctor`, `show`, and `storage list`.
Runtimeful generated commands use the app-owned `state_type` stored on
`ctx.obj`; bootstrapless generated commands use AppRC context metadata. AppRC
raises a clear error when that runtime state is missing after bootstrap, or when
the requested generated config group name already belongs to the host Typer app.

<br>

<!-- ======================================================== -->

<br>

## Doctor Statuses
<!-- ======================================================== -->

| Status | Meaning |
|---|---|
| `env_not_set` | Required selector env, usually storage, is missing. |
| `storage_not_ready` | Selected storage root or storage dotenv is missing or unusable. |
| `app_config_not_ready` | A default app-wide layer is expected but missing or unreadable. |
| `named_storage_not_ready` | A required named-storage index is missing, unreadable, invalid, or incompatible with the selector. |
| `runnable` | Runtime config can load. |

The JSON payload also includes `issues`, `warnings`, `missing_env_keys`, and
`next_steps`.

<br>

<!-- ======================================================== -->

<br>

## Dotenv Helper APIs
<!-- ======================================================== -->

Top-level facade helpers:

| Helper | Purpose |
|---|---|
| `EnvFileUpdate` | Result of one dotenv edit. |
| `read_env_file(path)` | Parse an optional dotenv file. Missing files return `{}`. |
| `write_env_file(path, values, owners=...)` | Write deterministic dotenv values. |
| `ensure_env_file(path)` | Create an explicit dotenv file if missing. |
| `set_env_file_value(...)` | Validate and write one value to an explicit dotenv path. |
| `clear_env_file_value(...)` | Remove one value from an explicit dotenv path. |
| `storage_env_path(root)` | Return `<root>/.env.apprc-storage`. |
| `ensure_storage_env_file(root)` | Create the storage dotenv file in an existing root. |
| `set_storage_env_value(...)` | Validate and write one storage value. |
| `clear_storage_env_value(...)` | Remove one storage value. |

References accepted by `set_*` and `clear_*` helpers:

- full env key, such as `MYAPP_PROFILE`
- dotted config path, such as `app.profile`
- unique field name, such as `profile`

<br>

<!-- ======================================================== -->

<br>

## Optional Logging APIs
<!-- ======================================================== -->

Root `apprc` names for optional logging:

| API | Purpose |
|---|---|
| `get_logger(name)` | Return an AppRC semantic logger for a new logger name. |
| `install_app_logger_class()` | Install AppRC's logger class for future stdlib loggers. |
| `setup_logging(...)` | Configure stdlib handlers and structlog processors. Requires `apprc[logging]`. |
| `LoggingConfig` | Dataclass for normalized logging setup. |
| `set_cid(value)` | Set correlation ID context. |
| `clear_cid()` | Clear correlation ID context. |
| `new_cid()` | Create and set a new correlation ID. |
| `log_init_lifecycle(...)` | Class decorator for initialization breadcrumbs. |

Renderer values for `setup_logging(renderer=...)`:

| Renderer | Output |
|---|---|
| `mini` | Compact human console output. |
| `cli` | CLI-oriented human console output. |
| `ipy` | Notebook-oriented human console output. |
| `json` | Machine-readable JSON records. |

<br>

# 3. Repository Reference

<!-- ======================================================== -->

<br>

## Project Paths
<!-- ======================================================== -->

| Path | Role |
|---|---|
| [README.md](../README.md) | Short adopter entry point and GitHub package documentation. |
| [README.pypi.md](../README.pypi.md) | Generated PyPI-safe README. |
| [AGENTS.md](../AGENTS.md) | Local coding and documentation guidance for agents. |
| [pyproject.toml](../pyproject.toml) | Package metadata, dependencies, and tool configuration. |
| [justfile](../justfile) | Development and release commands. |
| [src/apprc](../src/apprc) | Runtime package source. |
| [src/apprc_dev](../src/apprc_dev) | Repository-local development helpers. |
| [examples/apprc_example_app](../examples/apprc_example_app) | Runnable example host app. |
| [tests](../tests) | Test suite. |
| [docs](.) | Long-form documentation. |
| [assets](../assets) | Repository assets. |

<br>

<!-- ======================================================== -->

<br>

## Dependency Surfaces
<!-- ======================================================== -->

| Surface | File Section | Audience |
|---|---|---|
| Runtime dependencies | `[project].dependencies` | Users installing `apprc`. |
| Optional extras | `[project.optional-dependencies]` | Users opting into runtime feature stacks. |
| Dependency groups | `[dependency-groups]` | Maintainers running tests, linting, typing, docs, or profiling. |
| `uv` sources | `[tool.uv.sources]` | Local editable development sources. |
| Lock files | `uv.lock`, `pylock.toml` | Reproducible local and exported environments. |

<br>

<!-- ======================================================== -->

<br>

## Documentation Assets
<!-- ======================================================== -->

Docs assets live in [docs/assets](assets).

| Asset | Generator | Purpose |
|---|---|---|
| `docs-reading-map.svg` | [docs_reading_map.py](assets/docs_reading_map.py) | Shows how the root README routes readers into the docs scaffold. |
| `apprc-runtime-layers.svg` | [apprc_runtime_layers.py](assets/apprc_runtime_layers.py) | Shows the AppRC contract flowing into runtime and generated interfaces. |
| `apprc-abstract-user-journey.svg` | [apprc_abstract_user_journey.py](assets/apprc_abstract_user_journey.py) | README graphical abstract for developer and operator journeys. |
| `apprc-abstract-contract-workflows.svg` | [apprc_abstract_contract_workflows.py](assets/apprc_abstract_contract_workflows.py) | Shows one AppRC contract feeding runtime and generated workflows. |
| `apprc-abstract-layer-cake.svg` | [apprc_abstract_layer_cake.py](assets/apprc_abstract_layer_cake.py) | Shows dotenv and environment precedence during bootstrap. |
| `apprc-storage-config-locations.svg` | [apprc_storage_config_locations.py](assets/apprc_storage_config_locations.py) | Shows AppRC dotenv locations and which kit shapes use them. |

Keep assets simple and readable in GitHub light and dark themes. Update the
caption in the owning Markdown file when an asset changes meaning.
Use [render_all.py](assets/render_all.py) to regenerate all Graphigs-backed
docs figures.
