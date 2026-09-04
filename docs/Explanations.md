# AppRC Explanations

## Table of contents

1. [System model](#system-model)
2. [Integration flow](#integration-flow)
3. [Runtime config model](#runtime-config-model)
4. [AppRC directory and storage](#apprc-directory-and-storage)
5. [Runtime bootstrap](#runtime-bootstrap)
6. [Storage selection](#storage-selection)
7. [Zero-write and purge policy](#zero-write-and-purge-policy)
8. [Generated interfaces](#generated-interfaces)
9. [Migration model](#migration-model)

Use [How-To User Guides](How-To-User-Guides.md) for procedures and
[References](References.md) for exact names.

## System model

An application declares typed settings once. AppRC reuses that declaration for
runtime binding, dotenv precedence, validation, diagnostics, generated Typer
commands, the Textual editor, and provenance.

| ![AppRC runtime layers](assets/apprc-runtime-layers.svg) |
|:--:|
| **Fig. 1 — Runtime binding:** Bootstrap optionally adds managed dotenv values to the process environment; `Config()` binds that environment and Python values into a mutable object. |

The main objects have narrow jobs:

- `rc.AppRC` owns application identity and the optional storage capability.
- `rc.Storage` declares that the app needs persistent user data.
- `rc.Config` holds env-backed typed settings.
- `rc.ConfigBase` holds Python-only settings.
- `@MyRC.config(...)` registers a config section.
- `rc.field(...)` records the full env key and editing metadata.
- `@MyRC.bundle` builds one eager top-level config object.

There is no capability matrix. `rc.AppRC(...)` is storage-free;
`rc.AppRC(..., storage=rc.Storage())` supports storage. Files on disk never
enable a capability that Python code did not declare.

## Integration flow

The normal order is:

1. Create `rc.AppRC(...)`, with `storage=rc.Storage()` when needed.
2. Register `rc.Config` and `rc.ConfigBase` classes.
3. Ship non-secret defaults in `apprc.defaults.env`.
4. Mount the generated CLI or call bootstrap at the application entrypoint.
5. Run `config setup` during installation or first use.
6. Construct config from Python values and the current process environment.

Importing AppRC or a config class does not read files and does not modify
`os.environ`. Bootstrap is the explicit boundary where dotenv values enter the
current Python process. Constructing `Config()` then reads that environment.

## Runtime config model

Every registered env-backed section has an env prefix and ordered fields.
Every field has a Python type, full env key, required/default behavior,
editability, secrecy, choices, and explanatory text. The CLI and TUI use the
same metadata as runtime binding.

`rc.field("KEY")` is required when it has no default. `required=True` cannot be
combined with a Python `default` or `default_factory`. A required field may use
`packaged_default` to describe the corresponding value shipped in
`apprc.defaults.env`, or it may receive a constructor value. `secret=True`
controls display redaction only; it is not encryption.

Use exact file vocabulary in code and documentation. `apprc.user.env` and
`apprc.storage.env` are dotenv files, not generic “config files.”
`apprc.toml` is a storage registry. The directory containing the user dotenv
and registry is the AppRC directory.

## AppRC directory and storage

AppRC uses one predictable default on every operating system:

```text
~/.local/share/<app-id>/
```

The optional `<APP>_APPRC_DIR` variable relocates that complete directory. A
storage-free app normally contains only `apprc.user.env`. A storage-capable app
also contains `apprc.toml`; its initial registered root is
`~/.local/share/<app-id>/storage/`.

```text
~/.local/share/myapp/
├── apprc.user.env
├── apprc.toml
└── storage/
    └── apprc.storage.env
```

The initial storage is named `default`, but its directory is not nested below
another `default/` component. Later storage names are user-owned entries in
`apprc.toml`. Each may point anywhere. There is no separate “external storage”
feature; internal and external describe only where a registered root happens
to be, which matters during purge.

## Runtime bootstrap

Bootstrap performs these operations:

1. Capture the original process environment.
2. Read explicit `--env-file` values.
3. Resolve the AppRC directory.
4. Read packaged defaults and `apprc.user.env`.
5. Load `apprc.toml`, select a registered storage, and validate its root.
6. Read the selected `apprc.storage.env`.
7. Merge values using documented precedence.
8. Write the merged values into this Python process.
9. Record provenance for app-owned keys.

| ![AppRC precedence](assets/apprc-abstract-layer-cake.svg) |
|:--:|
| **Fig. 2 — Precedence:** Broad defaults sit below user, storage, invocation, and process-specific values. |

The parent shell is never modified. With normal precedence, existing
`os.environ` wins over explicit files. `--env-file-overrides-os-environ` makes
explicit files win instead.

`Config()` may also bind only constructor values, Python defaults, and the
current environment. Applications call `bootstrap(...)` when they own file and
storage policy. Libraries should accept an already constructed config object.
`ensure_bootstrapped()` is available only for high-level convenience
boundaries where default bootstrap policy is always correct.

## Storage selection

A selector is a registered name, never a filesystem path. Selection precedence
is:

1. `--storage NAME`
2. `<APP>_STORAGE=NAME` from the process or an explicit dotenv; the existing
   `--env-file-overrides-os-environ` option decides which of those wins
3. `selected_storage` in `apprc.toml`

Managed user, storage, and packaged dotenv files do not select storage. This
prevents persistent application data from silently moving because a dotenv
contains a path. The registry owns roots; relative roots resolve against the
directory containing `apprc.toml`, not the current working directory.

Registry lifecycle rules are shared by the CLI, editor, bootstrap, and doctor:

- the first added storage becomes selected;
- later additions preserve the selection;
- renaming the selected storage updates `selected_storage`;
- removing the selected storage clears selection and warns;
- duplicate names are rejected.

`repoint` changes only a registry path. `move` relocates the actual directory
transactionally and then updates the registry. These operations are separate
because combining them would hide whether user data moved.

## Zero-write and purge policy

Bootstrap, `config paths`, `config doctor`, opening `config edit`, and listing
storages are read-only. Setup, migration, purge, editor saves, and storage
registry commands write only after explicit user action.

Python package uninstallers do not own user files, so they leave the AppRC
directory and storage roots behind. `config purge --dry-run` shows what AppRC
can remove before the application is uninstalled.

Purge does not recursively delete `--apprc-dir`. It deletes only the fixed
AppRC files and registered storage roots strictly inside that directory.
External registered roots retain all data except their fixed
`apprc.storage.env`. Directories are removed only when empty, malformed TOML
stops the operation before deletion, and symlinks are never followed.

## Generated interfaces

The generated CLI and Textual editor are two views of the same contract. A
storage-free declaration has no `--storage`, `config storage ...`, storage
scope, or storage editor section. A stale `apprc.toml` does not change that;
doctor warns and purge can remove it.

A storage declaration exposes every registry entry. Storage names are not
declared in Python. The user adds, selects, renames, repoints, moves, and
removes them through the registry commands or editor.

## Migration model

AppRC 0.20 migrates only layouts released by 0.19. It scans the former
platform-specific config directory, declared legacy app IDs, custom
`<APP>_APPRC_TOML` locations, `.env.apprc-app`, `.env.apprc-storage`, and the
former `<app>.apprc.toml` filename.

A path-valued 0.19 `<APP>_STORAGE` becomes the root of a named `default`
storage. Structural path and TOML selectors are removed from the migrated user
dotenv. Exported process variables cannot be edited, so migration warns the
user to unset them. The unreleased `apprc.app.env` name is not a migration
source.

`config migrate` preflights every source and destination. A conflict stops the
whole operation. Moves never replace an existing destination and cross-device
fallback copies clean up partial destinations on failure.

Packaged defaults are source code owned by the host application. App authors
rename `.env.shared` to `apprc.defaults.env` in their repository; the runtime
command does not edit an installed package.
