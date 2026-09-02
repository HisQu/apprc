# AppRC Explanations

## Table of contents

1. [System model](#system-model)
2. [Integration flow](#integration-flow)
3. [Runtime config model](#3-runtime-config-model)
4. [Runtime bootstrap](#runtime-bootstrap)
5. [Storage selection](#storage-selection)
6. [Zero-write policy](#zero-write-policy)
7. [Generated interfaces](#generated-interfaces)
8. [Migration model](#migration-model)

Use [How-To User Guides](How-To-User-Guides.md) for procedures and
[References](References.md) for exact names.

## System model

An application declares typed settings once. AppRC reuses that declaration for
runtime binding, dotenv precedence, validation, diagnostics, generated Typer
commands, the Textual editor, and provenance.

| ![AppRC runtime layers](assets/apprc-runtime-layers.svg) |
|:--:|
| **Fig. 1 — Runtime layers:** One declaration feeds runtime setup and every user-facing config workflow. |

The main objects have narrow jobs:

- `rc.AppRC` owns application identity and optional storage.
- `rc.Storage` says that the app needs a persistent directory.
- `rc.Config` holds env-backed typed settings.
- `rc.ConfigBase` holds Python-only settings.
- `@MyRC.config(...)` registers a config section.
- `rc.field(...)` records the full env key and editing metadata.
- `@MyRC.bundle` builds one eager top-level config object.

There is no mode matrix in the primary API. Per-user app config is always
available and lazy. Storage is either absent or declared.

## Integration flow

The normal order is:

1. Create `rc.AppRC(...)`, with `storage=rc.Storage()` when needed.
2. Register `rc.Config` and `rc.ConfigBase` classes.
3. Ship non-secret defaults in `apprc.defaults.env`.
4. Mount AppRC on the CLI or call `bootstrap()` manually.
5. Construct runtime config after bootstrap.

Importing AppRC or a config class does not read files and does not modify
`os.environ`. Bootstrap is the explicit boundary where dotenv values enter the
current Python process.

## 3. Runtime config model

Every registered env-backed section has an env prefix and ordered fields.
Every field has a Python type, full env key, required/default behavior,
editability, secrecy, choices, and explanatory text. The CLI and TUI use the
same metadata as runtime binding, so there is no second UI schema to keep in
sync.

`rc.field("KEY")` is required when it has no default. `secret=True` controls
display redaction only; it is not encryption and does not change persistence.
`packaged_default` documents a deliberate difference between a Python fallback
and the value shipped in `apprc.defaults.env`.

Per-user app config is deliberately lazy. A config-only application needs no
installation step. The first app-scope save creates `apprc.app.env`.

Storage is separate because it represents application data ownership, not a
stronger kind of config. `rc.Storage()` adds selection, setup, local overrides,
and named-storage management without changing the config declaration model.

## Runtime bootstrap

Bootstrap performs these operations:

1. Capture the original process environment.
2. Read explicit `--env-file` values.
3. Resolve current or legacy managed filenames.
4. Read packaged defaults and per-user app config.
5. Select and validate storage when declared.
6. Read the selected storage dotenv.
7. Merge values using documented precedence.
8. Write the merged values into this Python process.
9. Record provenance for app-owned keys.

| ![AppRC precedence](assets/apprc-abstract-layer-cake.svg) |
|:--:|
| **Fig. 2 — Precedence:** Broad defaults sit below user, storage, invocation, and process-specific values. |

The parent shell is never modified. With normal precedence, existing
`os.environ` wins over explicit files. `--env-file-overrides-os-environ` makes
explicit files win instead.

## Storage selection

A storage selector answers one question: which directory owns persistent data
and `apprc.storage.env` for this run?

The selector can be:

- a direct path from `--storage`, the derived env key, or an explicit env file;
- a name stored in `apprc.toml`;
- the path persisted by first setup in `apprc.app.env`.

Direct paths do not require TOML. This keeps the single-storage case simple.
Named storage is an optional address book for applications that need several
roots. It becomes useful without becoming a separate capability level.

The default first storage suggestion comes from
`platformdirs.user_data_path(app_name, appauthor=False)`. This follows platform
conventions while remaining configurable through `Storage.suggested_root` and
`config setup --storage-root PATH`.

`--storage-root` is a path-typed option so shells can complete a custom path.
The short automatic prompt only asks whether to accept the suggestion. It does
not implement a weaker in-prompt path editor.

| ![Storage and config locations](assets/apprc-storage-config-locations.svg) |
|:--:|
| **Fig. 3 — File locations:** Packaged defaults, user config, AppRC TOML, and storage-local config have distinct owners. |

## Zero-write policy

Read operations stay read-only:

- `bootstrap()`
- `config paths`
- `config doctor`
- opening `config edit`
- listing storages

Writes occur only after an explicit command or confirmed editor action. The
automatic first-run prompt is part of a runtime command, but it asks before
creating anything. Declining prints the exact setup command and changes no
files.

This separation matters because help, diagnostics, tests, and routine startup
must not silently create configuration residue.

## Generated interfaces

The generated CLI and Textual editor are two views of the same contract.
`config setup` remains visible even when setup is unnecessary because it gives
users a stable discovery point and explains the declaration.

For a storage declaration, the editor can create the first storage from an
empty registry. It can also register the active path, rename a selector,
repoint its location, move its directory, archive it, restore it, and remove
it. These actions are based on storage state, not on old constructor names.

Diagnostics show the declaration directly: whether storage, app config, and
named storage are enabled, which files are selected, and what is needed next.
This is more useful than exposing internal optional/default capability levels.

## Migration model

AppRC 0.20 changes names without making existing installations unreadable.
Each managed file has a preferred path and ordered legacy candidates.

- If only the preferred file exists, AppRC uses it.
- If only a legacy file exists, AppRC continues reading and writing it.
- If both exist, the preferred file wins and AppRC warns.
- AppRC never merges competing files automatically.

`config migrate` preflights the app dotenv, AppRC TOML, the active storage, and
every registered storage before moving anything. A conflict stops the whole
operation. Each move reserves the current filename without replacement before
removing the legacy name. If the filesystem fails after some moves, the
command reports what completed and can be run again.

Packaged defaults are source code owned by the host application, so users do
not migrate them from an installed CLI. App authors rename `.env.shared` to
`apprc.defaults.env` in their repository. The runtime fallback protects the
transition.
