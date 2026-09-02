# Changelog

All notable changes to `AppRC` will be documented in this file.

> [!IMPORTANT]
> ## Rules
> 1) Do not remove or change this header and TOC without very good reason. 
> 1) When bumping version, move the sub-sections from `[Unreleased]` to
>    the new version -section. Remove empty sub-sections under released
>    versions. Provide a new `[Unreleased]` section at the top of the
>    changelog with all sections empty (don't remove those).
> 1) Do not remove emojis and use `<br>` and `---`.
> 1) Changelog entries must describe the final net difference from the
>    previous released version. Do not list intermediate pre-release
>    names, helper shapes, fixes, or refactors that were overwritten
>    before release.
> 1) Use `🔨 Fixed` only for defects in previously released behavior.
>    For new features, describe the final shipped behavior under `➕
>    Added`, even if the implementation went through pre-release fixes.




<br>

---

<br>

## Table Of Content

1. [Changelog](#changelog)
   1. [Table Of Content](#table-of-content)
2. [\[Unreleased\]](#unreleased)
3. [0.19.9 - 2026-09-02](#0199---2026-09-02)
4. [0.19.8 - 2026-09-01](#0198---2026-09-01)
5. [0.19.5 - 2026-07-14](#0195---2026-07-14)
6. [0.19.4 - 2026-07-13](#0194---2026-07-13)
7. [0.19.3 - 2026-07-13](#0193---2026-07-13)
8. [0.19.2 - 2026-07-13](#0192---2026-07-13)
9. [0.19.1 - 2026-07-03](#0191---2026-07-03)
10. [0.19.0 - 2026-07-03](#0190---2026-07-03)
11. [0.18.0 - 2026-07-02](#0180---2026-07-02)
12. [0.17.0 - 2026-07-01](#0170---2026-07-01)
13. [0.16.4 - 2026-06-30](#0164---2026-06-30)
14. [0.16.3 - 2026-06-29](#0163---2026-06-29)
15. [0.16.2 - 2026-06-28](#0162---2026-06-28)
16. [0.16.1 - 2026-06-27](#0161---2026-06-27)
17. [0.16.0 - 2026-06-26](#0160---2026-06-26)
18. [0.1.0 - 2026-06-02](#010---2026-06-02)

<br>

---

<br>

<!-- ======================================================== -->

# [Unreleased]

<br>

### 💥 Breaking changes

  - Breaking: `AppRC(...)` now declares an application directly and accepts
    optional `storage=rc.Storage(...)` instead of a `mode` argument.
    Affected: Users that instantiate `AppRC` directly or depend on the four
    capability levels as the primary public model.
    Migration: Remove `mode`, instantiate `rc.AppRC(...)` directly, and add
    `storage=rc.Storage(...)` only when the application owns persistent data.
    The `env_only`, `storage_only`, `app_wide_config`, and `app_wide_storage`
    class methods remain as deprecated 0.20 compatibility shims.

  - Breaking: Current declarations use `apprc.defaults.env`, `apprc.app.env`,
    `apprc.storage.env`, and `apprc.toml` as managed filenames.
    Affected: App authors shipping `.env.shared`, users with AppRC-managed
    dotenv files or `<app>.apprc.toml`, and integrations that assume the old
    default paths.
    Migration: Rename packaged `.env.shared` to `apprc.defaults.env`, then run
    `<app> config migrate` to move user-managed files. AppRC 0.20 continues to
    use an old file when the new file is absent; when both exist, the new file
    wins and AppRC reports the conflict instead of merging them.

  - Breaking: Machine-readable config output now uses the direct vocabulary,
    including `storage_enabled`, `app_config_enabled`, `app_env`,
    `storage_selector_env_key`, and `apprc_toml`; provenance uses
    `shell_dotenv_defaults` and `shell_dotenv_app`.
    Affected: Scripts that parse `config paths --json`, `config doctor --json`,
    `config storage list --json`, or serialized provenance values.
    Migration: Replace the former `capabilities`, `app_wide_*`, `storage_env_key`,
    and `index_*` keys and the `shell_dotenv_shared` and
    `shell_dotenv_app_wide` origin values with their direct-name equivalents.

  - Breaking: `apprc scaffold config` now selects only whether storage is
    present; `--mode` and `--storage-env-key` were removed.
    Affected: Scripts and documentation that invoke the config scaffold.
    Migration: Use `--storage` when persistent data is needed and
    `--storage-selector-env-key NAME` only to override the derived selector.

<br>

### ➕ Added

  - Added `rc.Storage(...)` for declaring storage selection, its managed
    dotenv filename, named-storage support, and first-run prompting without
    introducing another AppRC constructor.

  - Added `config migrate` with dry-run planning, whole-operation conflict
    preflight, no-replace execution checks, and migration of the app dotenv,
    AppRC TOML, active storage, and registered storage dotenv files. Blocking
    path types and destinations created after planning stop without data loss.

  - Added a first-run terminal prompt for storage-backed applications. It can
    create the platform-aware suggested data directory or decline without
    changing files. Custom paths remain available through the shell-completed
    `config setup --storage-root PATH` option. Failed setup removes only the
    artifacts created by that attempt and preserves pre-existing storage data.

  - Added storage creation, rename, location change, and directory move
    controls to the config editor for every storage-backed declaration. The
    existing `Setup` action remains visible for an explicit recovery path.

<br>

### 💔 Changed

  - Changed user-facing status, diagnostics, editor labels, examples, and
    documentation to explain the two independent facts directly: whether the
    app uses storage and whether a named storage is selected.

  - Changed the suggested storage root to the operating system's user data
    directory while keeping the proposed path visible and editable during
    first-run setup.

  - Changed the internal compatibility boundary so current declarations stay
    statically typed, legacy filename aliases retain basename validation, and
    deprecated capability vocabulary is isolated to compatibility code.

<br>

### ⚠️ Deprecated

  - Deprecated `AppRC.env_only(...)`, `AppRC.storage_only(...)`,
    `AppRC.app_wide_config(...)`, and `AppRC.app_wide_storage(...)`. They keep
    their 0.19 file and setup behavior in 0.20 and are scheduled for removal in
    0.21.

  - Deprecated Python read aliases that use `shared`, `app_wide`, `index`, or
    `storage_env_key` terminology. Use `defaults`, `app`, `apprc_toml`, and
    `storage_selector_env_key` names instead.

<br>

### 🗑️ Removed

<br>

### 🔨 Fixed

<br>

### 🔒 Security

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.9 - 2026-09-02

<br>

### ➕ Added

  - Added an actionable `Setup` button to every Textual config editor. It runs
    the declared env-only, app-wide, or storage setup route, reports required
    shell selectors, and optionally registers a new storage under a name.

<br>

### 🔨 Fixed

  - Fixed the Textual editor so storage-capable apps can create and register
    their first named storage without first creating the named-storage index
    through a separate CLI command. Opening the editor remains zero-write.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.8 - 2026-09-01

<br>

### 💥 Breaking Change Summary

  - Breaking: Runtime bootstrap now rejects selected storage roots that do not
    exist or are not directories.
    Affected: Python callers that create their storage directory after calling
    `AppConfigKit.bootstrap()` or `AppRC.bootstrap()`.
    Migration: Create the directory before bootstrap or run the owning
    application's `config setup --yes --storage-root STORAGE_ROOT` command.

<br>

### 💔 Changed

  - Updated Pyright to 1.1.411.

<br>

### 🔨 Fixed

  - Fixed storage-root failures so AppRC reports the owning application's
    display name and `config setup` command before dependent runtime objects
    are constructed.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.5 - 2026-07-14

<br>

### ➕ Added

  - Added Textual editor controls to rename named storages, repoint their
    registered locations, and move complete live storage directories.
    Repointing changes only the registry; moves accept only new or empty safe
    destinations, never merge or replace files, and leave the registry
    unchanged if a cross-filesystem source changes during copying. AppRC does
    not rewrite external `--storage`, environment, or dotenv selectors.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.4 - 2026-07-13

<br>

### 💔 Changed

  - Changed the maintainer release entrypoint from `just bump` to
    `just release` so its name reflects the full workflow. Its output now
    distinguishes local commit and tag preparation from publication, gives the
    exact tag-push command, and explains that GitHub publishes only after CI
    and protected-environment approval succeed.

<br>

### 🔨 Fixed

  - Fixed AppRC's automatic dataclass generation so registered config and
    bundle classes that define `__post_init__()` keep stable class identity.
    This preserves normal `super().__post_init__()` behavior on Python 3.12
    and 3.13 while keeping slotted dataclasses for classes without custom
    post-init hooks.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.3 - 2026-07-13

<br>

### ➕ Added

  - Added a tag-driven GitHub release pipeline that runs the complete CI
    matrix, validates and preserves release artifacts, pauses for approval,
    publishes to PyPI through Trusted Publishing, and creates a GitHub Release
    from the curated changelog notes.

<br>

### 💔 Changed

  - Changed release maintenance so `just bump` runs one complete local gate
    across Python 3.12 through 3.14 before committing or tagging, restores
    version files after failed checks, validates and smoke-tests the exact
    release artifacts, keeps temporary environment setup concise, and dry-runs
    publication without prompting for credentials before confirming that
    nothing was uploaded and printing the next release step. Repository
    metadata now links directly to the package, docs, changelog, and current
    project topics.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.2 - 2026-07-13

<br>

### 🔨 Fixed

  - Fixed `rc.ConfigBase` and `rc.Config` construction and inherited hooks on
    Python 3.12 and 3.13 when using slotted dataclass subclasses.

  - Fixed storage-root normalization so native Windows processes preserve
    rooted drive paths while POSIX and WSL retain Windows-drive conversion.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.1 - 2026-07-03

<br>

### 💔 Changed

  - Changed `apprc scaffold config` and repository example apps so generated
    config package facades resolve exports lazily, publish typed `.pyi`
    surfaces, and bundles import section classes from leaf modules. This keeps
    optional dependencies owned by one section from loading during unrelated
    config imports.

<br>

---

<br>

<!-- ======================================================== -->

# 0.19.0 - 2026-07-03

<br>

### 💥 Breaking Change Summary

  - Breaking: Replaced the root public API with the clean `import apprc as rc`
    facade: `rc.AppRC`, `rc.Config`, `rc.ConfigBase`, `rc.field`, and the
    `rc.cli`, `rc.files`, `rc.storage`, and `rc.provenance` namespaces.
    Affected: Users importing root names such as `AppConfigKit`, `EnvConfig`,
    `env_field`, `env_owner`, `mount_config_cli`, or storage/file helpers
    directly from `apprc`.
    Migration: Create `MyRC = rc.AppRC.<mode>(...)`, register env-backed
    classes with `@MyRC.config("key", prefix="FULL_PREFIX_")`, inherit
    `rc.Config`, declare fields with `rc.field("FULL_ENV_KEY", ...)`, inherit
    `rc.ConfigBase` for Python-only config, mount Typer with
    `MyRC.mount_cli(app)`, and use namespace modules for advanced helpers.

  - Breaking: Removed legacy lower-level aggregate facade exports from
    `apprc.definition`, `apprc.runtime`, `apprc.user_files`, and
    `apprc.user_files.storage_roots`.
    Affected: Users importing supported-looking symbols such as
    `AppConfigKit`, `ConfigOwner`, `EnvBootstrapResult`, `StorageRegistry`,
    or `register_storage` from those aggregate packages.
    Migration: Use `import apprc as rc` with `rc.AppRC`, `rc.Config`,
    `rc.field`, `rc.schema`, `rc.provenance`, `rc.files`, and `rc.storage`.
    Concrete implementation modules remain importable for AppRC internals but
    are not the public integration surface.

  - Breaking: Removed the app-specific `apprc.utils.huggingface` helper
    module.
    Affected: Users importing `apprc.utils.huggingface` directly.
    Migration: Move Hugging Face synchronization helpers into the application
    or a dedicated application dependency.

  - Breaking: Removed selector-unaware config CLI hooks.
    Affected: Users passing `active_storage_root=` or `initial_storage=` to
    `AppConfigKit.typer_app(...)`, `rc.cli.mount_config_cli(...)`,
    `rc.cli.build_config_typer_app(...)`, or `rc.cli.CliRuntime(...)`.
    Migration: Use `active_storage_root_with_context=` or
    `initial_storage_with_context=`. The hook may ignore
    `ConfigSelectorContext` when it only needs app state.

  - Breaking: Moved the Textual editor dependency to the optional `tui` extra.
    Affected: Users installing base `apprc` and running generated
    `config edit` commands or importing TUI classes such as
    `rc.cli.ConfigEditorApp`.
    Migration: Install AppRC with `python -m pip install "apprc[tui]"` or add
    `apprc[tui]` to the application's dependency declaration.

  - Breaking: Moved generated repository example app disk files from root
    `.apprc-example-*` directories to
    `examples/example_app_disk_files/.apprc-example-*`.
    Affected: Maintainers and local scripts sourcing files such as
    `.apprc-example-storage-only/.env`.
    Migration: Source `.env.example_apps` and run
    `python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"`,
    or use direnv so `.envrc` does both automatically.

  - Breaking: Renamed repository-local example import packages to short names:
    `env_only`, `storage_only`, `app_wide_config`, `app_wide_storage`,
    `explicit_env_precedence`, `cli_runtime`, and `_example_apps_utils`.
    Affected: Maintainers, tests, or local tools importing the old
    `apprc_*_example` packages or `apprc_example_apps`.
    Migration: Update imports to the short package names. Console scripts,
    AppRC app names, and `APPRC_EXAMPLE_*` env vars are unchanged.

<br>

### ➕ Added

  - Added the public `rc.schema` namespace for read-only AppRC contract
    metadata used by advanced documentation, inventory, and diagnostics
    integrations.

  - Added the first-party `apprc` CLI with `apprc scaffold config` for
    generating the recommended `X.config` package layout.

  - Added tracked `.env.example_apps` defaults plus `.envrc` auto-bootstrap so
    repository example CLIs can run from one sourced root environment.

<br>

### 💔 Changed

  - Changed `@MyRC.bundle` to support dataclass `init=False` config fields and
    user `__post_init__()` hooks so applications can derive registered child
    configs from eagerly resolved siblings without leaving the bundle
    interface.

  - Changed repository example apps to use app-local `config/` packages with
    `app.py`, `sections/`, `bundle.py`, `catalog.py`, and packaged
    `config/.env.shared` defaults. Complex config areas now live as nested
    packages under `sections/`, as shown by the CLI runtime example.

  - Changed the example app tree to separate runnable source packages under
    `examples/example_apps` from ignored generated disk files under
    `examples/example_app_disk_files`.

  - Changed config editor storage workflow ownership so archive import and
    archive/delete orchestration live on the coordinator instead of relying on
    runtime stubs inherited by leaf workflow classes.

  - Changed release maintenance helpers so `just verify-pypi` checks the
    current base public API and optional `tui` metadata, `just clean` removes
    nested package metadata, and lazy facade type surfaces live in `.pyi`
    stubs.

  - Changed the source distribution to include `examples/example_apps/**`
    alongside `tests/**` so downstream sdist test runs have the repository
    example packages they import.

  - Changed the generated PyPI README to rewrite repository-relative docs,
    example, and asset links to GitHub URLs.

<br>

### 🔨 Fixed

  - Fixed the CI compile step so it covers current source roots with
    `src`, `tests`, and `examples/example_apps/src`.

  - Fixed stale release-facing prose by replacing the changelog template name,
    removing the removed logging package owner row, and updating the justfile
    optional-extra example to `tui`.

  - Fixed failed storage registration rollback so cleanup failures are logged,
    attached to the original exception as notes, and shown as warning
    notifications in the config editor.

<br>

---

<br>

<!-- ======================================================== -->

# 0.18.0 - 2026-07-02

<br>

### 💥 Breaking Change Summary

  - Breaking: Removed AppRC's semantic logging package and root logging
    facade exports.
    Affected: Users importing `apprc.logging`, `apprc.get_logger`,
    `apprc.setup_logging`, `apprc.AppLogger`, `apprc.LoggingConfig`, or
    related logging helpers from AppRC.
    Migration: Add `holylog` as an application dependency and use
    `import holylog as hlog`, then call `hlog.setup_logging(...)` and
    `hlog.get_logger(...)`. AppRC's CLI runtime setup still accepts an
    app-owned `setup_logging` callable.

  - Breaking: Renamed the composable Typer bridge/bootstrap API to CLI runtime
    terminology and removed compatibility aliases.
    Affected: Users importing or calling `ConfigCliBridge`,
    `ConfigCliSession`, `HostCliBootstrapPolicy`, `BootstraplessCommand`,
    `CliBootstrapContext`, `CliBootstrapOptions`,
    `ConfigBootstrapPolicy`, `bootstrap_policy=...`,
    `prepare_typer_context(...)`, `apprc_context_from(...)`, or
    `apprc_options_to_args(...)`.
    Migration: Use `CliRuntime`, `CliRuntimeSession`,
    `CliRuntimePolicy`, `RuntimeIndependentCommand`,
    `CliRuntimeContext`, `CliRuntimeOptions`, `ConfigRuntimePolicy`,
    `runtime_policy=...`, `prepare_cli_runtime_context(...)`,
    `cli_runtime_context_from(...)`, and
    `cli_runtime_options_to_args(...)`.

  - Breaking: Changed `ConfigDoctorPayload` from a dictionary-shaped
    `TypedDict` to a dataclass model.
    Affected: Users indexing the result of
    `build_config_doctor_payload(...)` directly.
    Migration: Read dataclass attributes such as `payload.status`, or call
    `payload.to_payload()` when a JSON-friendly dictionary is needed.

  - Breaking: Made `DefaultConfigCliState` keyword-only so applications can
    subclass it with required fields.
    Affected: Users constructing `DefaultConfigCliState` with positional
    arguments.
    Migration: Pass `env_bootstrap=...` and `storage=...` by keyword, and
    inherit from `DefaultConfigCliState` for app-owned config CLI state.

<br>

### ➕ Added

  - Added `cli_options_from(ctx, OptionsType)` so runtime-independent commands
    can recover the full app CLI option object preserved by `CliRuntime`.

  - Added `CliRuntime.forwarded_args(...)` and
    `CliRuntime.run_forwarded(...)` for nested in-process Typer CLIs whose
    child runtime policy must inspect forwarded child arguments.

  - Added a dev-only `apprc_example_apps` registry helper exposing the
    repository-local example kits and bootstrap metadata.

  - Added a root facade snapshot test so changes to `apprc.__all__` are
    explicit and reviewable.

<br>

### 💔 Changed

  - Changed generated config diagnostics to use a typed
    `ConfigDoctorPayload` model internally while keeping explicit JSON
    serialization through `to_payload()`.

  - Changed the config editor storage workflows into action-specific
    registration, archive, and removal modules behind the existing
    `ConfigEditorStorageWorkflows` entrypoint.

  - Changed the remaining lazy aggregate facades into documented import-cycle
    boundaries after verifying that `apprc.runtime`, `apprc.user_files`, and
    `apprc.user_files.storage_roots` still require lazy loading.

<br>

---

<br>

<!-- ======================================================== -->

# 0.17.0 - 2026-07-01

<br>

### 💥 Breaking Change Summary

  - Breaking: Replaced the old `apprc.runtime_config` and `apprc.cli`
    public import paths with the clearer `definition`, `runtime`,
    `user_files`, and `interfaces` architecture.
    Affected: Users importing AppRC internals from `apprc.runtime_config.*`
    or `apprc.cli.*`.
    Migration: Prefer one root import, `import apprc`, and access stable
    integration APIs through that handle, such as `apprc.AppConfigKit`,
    `apprc.EnvConfig`, `apprc.mount_config_cli`, and
    `apprc.build_config_doctor_payload`. Advanced internal imports now live
    under `apprc.definition`, `apprc.runtime`, `apprc.user_files`, and
    `apprc.interfaces`.

  - Breaking: Removed the repository-local `apprc_example_app` demo package
    and its ambiguous `apprc` console script.
    Affected: Maintainers or downstream test harnesses using the checkout's
    old `examples/apprc_example_app` package or `apprc` demo executable.
    Migration: Use the new dev-only `apprc-example-apps` package and its
    explicit scripts, such as `apprc-storage-only config doctor`,
    `apprc-app-wide-storage config show`, or
    `apprc-cli-bridge status`.

<br>

### ➕ Added

  - Added executable capability-mode examples under
    `examples/example_apps`, covering `env_only`, `storage_only`,
    `app_wide_config`, `app_wide_storage`, named storage, explicit env-file
    selector precedence, and the `ConfigCliBridge` host-callback path. Each
    example lives in its own import package with local config declarations,
    `cli.py`, and `.env.shared` files, matching the structure downstream apps
    should use.

  - Added `python -m apprc_dev.example_apps.bootstrap` to create ignored
    example sandboxes with commented `.env`, `.env.apprc-app`,
    `.env.apprc-storage`, and `.apprc.toml` files.


<br>

### 💔 Changed

  - Changed AppRC's package tree to make ownership visible from paths:
    declarations live in `apprc.definition`, process-time behavior in
    `apprc.runtime`, managed user files in `apprc.user_files`, and CLI/TUI
    surfaces in `apprc.interfaces`.

  - Changed the root `apprc` facade into the stable application import surface
    for config definitions, runtime bootstrap, diagnostics, generated CLI
    integration, TUI app classes, dotenv helpers, storage helpers, and optional
    logging.

<br>

### 🗑️ Removed

  - Removed the old `apprc.runtime_config` and `apprc.cli` compatibility
    packages after moving their implementation into the new architecture.


---

<br>

<!-- ======================================================== -->

# 0.16.4 - 2026-06-30

<br>

### ➕ Added

  - Added `ConfigCliBridge`, `ConfigCliSession`, `ConfigCliStateFactory`,
    `BootstraplessCommand`, `HostCliBootstrapPolicy`, and
    `MountConfigCliStateFactory` for apps that need a composable Typer
    integration layer around custom host callbacks.

  - Added a Graphigs-backed structured dotenv/config-file map showing where
    AppRC keeps each `.env` and TOML file, which `AppConfigKit` shapes use
    them, and how startup inputs feed runtime config.

<br>

### 💔 Changed

  - Changed `mount_config_cli(...)` and `ConfigCliBridge(...)` so the shipped
    behavior includes default `DefaultConfigCliState` support, explicit
    `state_factory` support for app-owned runtime state, custom generated
    config group names, explicit argv/policy injection for tests and forwarding
    CLIs, help-safe bootstrap skipping, generated config group collision
    checks, and context-only handling for bootstrapless generated config
    commands.

  - Changed CLI bridge docs and config selector wording to use host-level
    option terminology consistently.

<br>

### 🔨 Fixed

  - Fixed host and generated-config help parsing so structurally recognized
    help such as `run --help` can render without runtime storage, while
    help-like option values such as `--text --help` and separator-protected
    tokens such as `run -- --help` remain runtime data.

  - Fixed bridge skip-policy composition so app-specific host option sets
    extend AppRC's standard options, generated config commands strip those
    custom host options correctly, and direct config bootstrap policies cannot
    drift from the bridge config group name.

  - Fixed bootstrapless host-command declarations so empty action tuples are
    rejected clearly; use `skip_empty=True` for bare command groups.

  - Fixed runtimeful generated config commands with custom state so they fail
    clearly when AppRC bootstrap ran but the host callback did not leave the
    declared `state_type` on `ctx.obj`, while bootstrapless config commands
    still use AppRC's stored context.

  - Fixed generated config group mounting so `ConfigCliBridge(...)` and
    `mount_config_cli(...)` reject host Typer apps that already own the
    requested config command or group name.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.3 - 2026-06-29

<br>

### ➕ Added

  - Added layered Typer integration helpers: `mount_config_cli(...)`,
    `CliBootstrapOptions`, AppRC Typer context metadata, reusable root option
    aliases, and configurable config bootstrap skip policies.

  - Added Graphigs-backed docs figure scripts for regenerating
    `docs-reading-map.svg` and `apprc-runtime-layers.svg`.

  - Added and placed Graphigs-backed graphical abstracts for the README
    overview, README system model, and runtime bootstrap docs.

<br>

### 💔 Changed

  - Improved Graphigs-backed graphical abstract layouts with clearer groups,
    a wide README hero format, looser labels, and documented figure color
    roles.

  - Tightened the new Typer convenience helper API before its first release:
    custom `mount_config_cli(...)` state now requires `state_factory=...`,
    generated config group renaming uses `config_group_name=...`, and explicit
    mount hook parameters replace loose keyword forwarding.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.2 - 2026-06-28

<br>

### 💥 Breaking Change Summary

  - Breaking: `get_logger(NAME)` now raises `RuntimeError` when `NAME` already
    belongs to a pre-existing non-`AppLogger`.
    Affected: Integrations that create stdlib loggers before requesting an
    AppRC semantic logger for the same name.
    Migration: Call `install_app_logger_class()` or `get_logger(NAME)` before
    `logging.getLogger(NAME)` for names that need AppRC semantic helpers, or
    keep using the existing plain logger directly.

  - Breaking: `extract_archive(...)` now refuses to restore into a non-empty
    destination unless `replace_existing=True` is passed.
    Affected: Integrations that called `extract_archive()` to merge or replace
    existing directories.
    Migration: Restore into an empty directory, or prompt/confirm externally
    before calling `extract_archive(..., replace_existing=True)`.

  - Breaking: Blank or whitespace-only storage root text now raises
    `StorageRootPathError` instead of resolving to the current directory.
    Affected: CLI or API callers passing `""` or whitespace as a storage root.
    Migration: Pass `.` explicitly when the current directory is intended.

<br>

### ➕ Added

  - Added public `ConfigSelectorContext` plus context-aware config hooks:
    `active_storage_root_with_context(state, selector_context)` and
    `initial_storage_with_context(state, selector_context)`.

  - Added `replace_existing=False` to `extract_archive(...)` so callers must
    opt in before replacing a non-empty destination.


<br>

### 🔨 Fixed

  - Fixed storage-free generated `config edit` commands so app state objects no
    longer need to define a storage selector field.

  - Fixed storage archive creation so symlinks and in-archive hardlinks are
    rejected before any archive file is written.

  - Fixed generated `config --help` and `<config subcommand> --help` so help
    output does not require runtime storage readiness.

  - Fixed skipped-bootstrap config commands so host-level `--env-file` storage
    selectors and `--env-file-overrides-os-environ` participate in storage
    selection without mutating `os.environ`.

  - Fixed `config storage add` and `config storage remove` so root
    `--env-file` values can select the named-storage index through
    `<APP>_APPRC_TOML`.

  - Fixed storage setup, registry writes, selector resolution, and TUI storage
    registration so blank storage roots are rejected consistently.

  - Fixed storage registration so corrupt existing registries are detected
    before storage directories or dotenv files are created.

  - Fixed storage registration rollback so failed registry writes remove only
    empty artifacts created by that call and preserve existing storage content.

  - Fixed archive restore so all members are validated before extraction, the
    restore is staged in a sibling temp directory, and non-empty destinations
    are replaced only after an explicit opt-in.

  - Fixed TUI storage deletion so the registry row is removed before directory
    deletion; deletion failures now warn without recreating the row.

  - Fixed config help detection to honor custom host-level value options and to
    ignore `--help` or `-h` after a `--` separator.


<br>

---

<br>

<!-- ======================================================== -->

# 0.16.1 - 2026-06-27

<br>

### 💥 Breaking Change Summary

  - Breaking: `StorageMode` and `storage_mode=` were removed from the public
    API.
    Affected: Integrations importing `StorageMode` or passing `storage_mode=`.
    Migration: Use `AppConfigKit.env_only(...)`,
    `AppConfigKit.storage_only(...)`, `AppConfigKit.app_wide_config(...)`, or
    `AppConfigKit.app_wide_storage(...)`.

  - Breaking: AppRC no longer reads or writes `.env.global` and `.env.local`.
    Affected: Users with existing app-wide values in `.env.global` or
    storage values in `.env.local`.
    Migration: Move app-wide values to `.env.apprc-app` and storage values to
    `.env.apprc-storage`. `config doctor` reports legacy-file warnings.

  - Breaking: Runtime bootstrap, `config paths`, `config doctor`, and editor
    open are zero-write.
    Affected: Users and tests that expected normal runtime reads to create the
    config home, app-wide dotenv, storage dotenv, or `<app>.apprc.toml`.
    Migration: Run `config app init`, `config setup`, or
    `config storage add NAME PATH` when files should be created.

  - Breaking: Top-level generated storage commands were removed.
    Affected: Users running `config init` or `config list`.
    Migration: Use `config storage add NAME PATH`,
    `config storage list`, and `config storage remove NAME`.

  - Breaking: App-wide and storage writes now use explicit scopes when both
    writable layers are active.
    Affected: Users running `config set KEY VALUE` after activating both
    `.env.apprc-app` and a storage root.
    Migration: Pass `--scope app` or `--scope storage`.

  - Breaking: The Textual editor no longer infers a write target when
    app-wide and storage scopes are both writable.
    Affected: Users pressing Enter or Ctrl+S in the value editor while both
    writable layers are active.
    Migration: Click `Save App-wide` or `Save Storage`.

  - Breaking: Public filename constructor arguments were renamed.
    Affected: Integrations passing `apprc_toml_filename`,
    `global_env_filename`, or `local_env_filename`.
    Migration: Use `index_filename`, `app_wide_env_filename`, and
    `storage_env_filename`.

  - Breaking: Public local-env helper names were removed.
    Affected: Integrations importing `LocalEnvUpdate`, `local_env_path`,
    `read_local_env`, `write_local_env`, `set_local_env_value`, or
    `clear_local_env_value` from AppRC facades or storage modules.
    Migration: Use `EnvFileUpdate`, `storage_env_path`, `read_env_file`,
    `write_env_file`, `set_storage_env_value`, and
    `clear_storage_env_value`. Use `set_env_file_value` and
    `clear_env_file_value` for app-wide or other explicit env-file paths.

<br>

### ➕ Added

  - Added explicit capability constructors:
    `AppConfigKit.env_only(...)`, `AppConfigKit.storage_only(...)`,
    `AppConfigKit.app_wide_config(...)`, and
    `AppConfigKit.app_wide_storage(...)`.

  - Added `config paths` to show declared capabilities, active layers,
    candidate paths, selected storage, named-storage index status, and
    `writes: none`.

  - Added `config app init`, `config storage add NAME PATH`,
    `config storage list`, and `config storage remove NAME`.

  - Added doctor statuses `app_config_not_ready` and
    `named_storage_not_ready`.

<br>

### 💔 Changed

  - Changed runtime bootstrap precedence to packaged `.env.shared`,
    app-wide `.env.apprc-app`, storage `.env.apprc-storage`, explicit env
    files, and existing `os.environ`.

  - Changed storage selector resolution so path selectors work without a
    named-storage index, while named selectors use `<app>.apprc.toml` only when
    the index is allowed and exists.

  - Changed the Textual editor to show layer-oriented source columns:
    `Effective`, `Shell`, `App-wide`, `Storage`, `Default`, and `Explanation`.

  - Changed `<APP>_APPRC_TOML` to mean only named-storage index relocation.

  - Changed `config setup` to follow the constructor instead of prompting for
    optional upgrades.

  - Changed the Textual editor to hide named-storage management controls when
    named storage is disabled, while keeping active path editing available.

<br>

### 🗑️ Removed

  - Removed `StorageMode`.

  - Removed `config init` and `config list`.

  - Removed `.env.global` and `.env.local` fallback reads.

<br>

### 🔨 Fixed

  - Fixed storage-only runtime use so a single `APP_STORAGE=/path` selector no
    longer requires a config-home file or named-storage index.

  - Fixed optional named-storage handling so path selectors ignore corrupt
    optional indexes at runtime and report them as doctor warnings, while bare
    named selectors fail only when they need the invalid index.

  - Fixed `config edit` so host-level storage selectors are honored and editor open
    remains zero-write when optional named-storage indexes are corrupt but not
    needed.

  - Fixed `config doctor` so corrupt optional indexes are warnings when no
    selector exists or the active selector is path-like.

  - Fixed storage-env helper writes so storage roots must already exist, and
    no-op clears no longer create empty dotenv files.

  - Fixed `config setup` for app-wide storage constructors so config-home
    errors are reported as clean CLI validation errors.

  - Fixed Textual editor source-copy buttons so app-wide and storage copy
    actions copy only actual source values.

<br>

---

<br>

<!-- ======================================================== -->

# 0.16.0 - 2026-06-26

<br>

### 💥 Breaking Change Summary

  - Breaking: `setup_logging()` now requires the `apprc[logging]`
    optional dependency because `structlog` is no longer installed by the base
    package.
    Affected: Users calling `setup_logging()` after installing bare `apprc`.
    Migration: Install AppRC with `python -m pip install "apprc[logging]"` or
    add `apprc[logging]` to the application's dependency declaration.

<br>

---

<br>

<!-- ======================================================== -->

# 0.1.0 - 2026-06-02

<br>

### ➕ Added

- Released `apprc`.
- Added src-layout packaging, Typer CLI entrypoints, AppRC configuration, documentation, tests, and maintainer tooling.
