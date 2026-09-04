# AppRC Reference

## Table of contents

1. [Public interfaces](#public-interfaces)
2. [Application declaration](#application-declaration)
3. [Configuration files](#configuration-files)
4. [Environment variables](#environment-variables)
5. [Runtime precedence](#runtime-precedence)
6. [Storage registry behavior](#storage-registry-behavior)
7. [Generated CLI commands](#generated-cli-commands)
8. [Doctor statuses](#doctor-statuses)
9. [Dependency surfaces](#dependency-surfaces)
10. [Documentation assets](#documentation-assets)

Use [How-To User Guides](How-To-User-Guides.md) for procedures and
[Explanations](Explanations.md) for design rationale.

## Public interfaces

Normal integrations use `import apprc as rc`.

| Name | Purpose |
| --- | --- |
| `rc.AppRC` | Declares one application, registers config, bootstraps runtime state, and mounts generated commands. |
| `rc.Storage` | Enables storage and optionally declares its selector environment key. |
| `rc.Config` | Base for env-backed typed config. |
| `rc.ConfigBase` | Base for Python-only config. |
| `rc.field` | Declares one env-backed field with a full environment key. |
| `rc.cli` | Advanced Typer runtime and mount helpers. |
| `rc.files` | Dotenv and managed-file helpers. |
| `rc.storage` | Storage registry, selector, and archive helpers. |
| `rc.provenance` | Runtime value-origin helpers. |
| `rc.schema` | Read-only config metadata. |

`rc.field(...)` accepts `default`, `default_factory`, `required`, `title`,
`description`, `editable`, `secret`, `choices`, and `packaged_default`.
`required=True` cannot be combined with `default` or `default_factory`.

## Application declaration

```python
MyRC = rc.AppRC(
    app_id="myapp",
    config_package="myapp.config",
    display_name="My App",
    command_name="myapp",
    storage=rc.Storage(selector_env_key="MYAPP_STORAGE"),
    apprc_dir_env_key="MYAPP_APPRC_DIR",
    legacy_app_ids=("old-myapp",),
)
```

`AppRC` arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `app_id` | required | Stable identity used for the default directory and derived keys. |
| `config_package` | required | Import package containing `apprc.defaults.env`. |
| `display_name` | `app_id` | Label shown to users. |
| `command_name` | `None`, rendered as `app_id` | Executable shown in generated instructions. |
| `storage` | `None` | `rc.Storage(...)` when the application persists user data. |
| `apprc_dir` | `None` | Application-declared AppRC directory override. |
| `apprc_dir_env_key` | derived `<APP>_APPRC_DIR` | Explicit environment key that relocates the AppRC directory. |
| `legacy_app_ids` | `()` | Released 0.19 identities scanned by migration. |

`Storage` has one argument:

| Argument | Default | Meaning |
| --- | --- | --- |
| `selector_env_key` | derived `<APP>_STORAGE` | Environment key that may select a registered storage name. |

Managed filenames are fixed. There is no filename or path-abstraction API.

## Configuration files

For `app_id="myapp"`:

| File | Location | Role |
| --- | --- | --- |
| `apprc.defaults.env` | `config_package` | Non-secret defaults shipped by the app. |
| `apprc.user.env` | `~/.local/share/myapp/` | Per-user dotenv overrides; created empty by setup. |
| `apprc.toml` | `~/.local/share/myapp/` | Registered storage names, roots, and persistent selection. |
| `apprc.storage.env` | Each registered storage root | Storage-specific dotenv overrides. |

`MYAPP_APPRC_DIR=/some/path` changes both fixed user files to
`/some/path/apprc.user.env` and `/some/path/apprc.toml`. It does not alter
storage roots recorded in the TOML.

The default first storage is:

```toml
selected_storage = "default"

[storages.default]
root = "/home/user/.local/share/myapp/storage"
```

Relative `root` values resolve against the directory containing `apprc.toml`.

## Environment variables

For `app_id="myapp"`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `MYAPP_APPRC_DIR` | No | Relocate the complete AppRC directory. |
| `MYAPP_STORAGE` | No when `selected_storage` exists | Override the selected storage with a registered name. Paths are rejected. |
| App-declared keys | Defined by each field | Typed runtime settings such as `MYAPP_PROFILE`. |

`MYAPP_STORAGE` is structural input during selection. After bootstrap resolves
the name, an app config field using that same key receives the concrete root.
Do not put storage selectors in `apprc.user.env`, `apprc.storage.env`, or
packaged defaults.

## Runtime precedence

Later rows win unless noted:

| Order | Dotenv value source |
| --- | --- |
| 1 | Packaged `apprc.defaults.env` |
| 2 | Per-user `apprc.user.env` |
| 3 | Selected storage `apprc.storage.env` |
| 4 | Explicit `--env-file` values, in argument order |
| 5 | Existing `os.environ` |

`--env-file-overrides-os-environ` swaps the final two positions.

Storage selection has a separate, narrower order:

1. `--storage NAME`
2. process or explicit-dotenv `<APP>_STORAGE=NAME`, using the same conditional
   precedence option
3. `selected_storage` in `apprc.toml`

Provenance emitted for dotenv values uses `shell_dotenv_defaults`,
`shell_dotenv_user`, `shell_dotenv_storage`, and `shell_dotenv_explicit`.

## Storage registry behavior

| Operation | Registry effect | Filesystem effect |
| --- | --- | --- |
| `add NAME ROOT` | Adds a unique name; the first entry becomes selected. | Creates the root and empty `apprc.storage.env`. |
| `select NAME` | Sets `selected_storage`. | None. |
| `rename NAME NEW_NAME` | Renames the record and updates selection when needed. | None. |
| `repoint NAME ROOT` | Changes only the recorded root. | None. |
| `move NAME DESTINATION` | Updates the root after a transactional move. | Moves the complete directory; never merges into non-empty data. |
| `remove NAME` | Removes the record; clears selection and warns when selected. | Leaves the root and its files in place. |

Individual storage names are user-maintained data. Python code declares only
whether storage is supported.

## Generated CLI commands

| Command | Availability | Writes | Purpose |
| --- | --- | --- | --- |
| `config paths [--json]` | All apps | No | Show declared paths. |
| `config doctor [--json]` | All apps | No | Diagnose readiness and give next steps. |
| `config show [--json]` | All apps | No | Show resolved runtime config. |
| `config setup [-y]` | All apps | Yes | Create the empty user dotenv. |
| `config setup [--storage-root PATH] [-y]` | Storage apps | Yes | Also register and select initial storage. |
| `config migrate [--dry-run] [-y]` | All apps | Unless dry-run or cancelled | Migrate released 0.19 files after full preflight. |
| `config purge [--dry-run] [-y]` | All apps | Unless dry-run or cancelled | Remove fixed AppRC files and registered internal roots. |
| `config set KEY VALUE --scope user` | All apps | Yes | Validate and save one user dotenv override. |
| `config set KEY VALUE --scope storage` | Storage apps | Yes | Validate and save one storage dotenv override. |
| `config edit` | All apps | Opening: no | Open the Textual editor; confirmed actions may write. |
| `config storage add NAME ROOT` | Storage apps | Yes | Register a unique storage and initialize its dotenv. |
| `config storage list [--json]` | Storage apps | No | List registered roots. |
| `config storage select NAME` | Storage apps | Yes | Persist the selected name. |
| `config storage rename NAME NEW_NAME` | Storage apps | Yes | Rename registry metadata only. |
| `config storage repoint NAME ROOT` | Storage apps | Yes | Change registry metadata only. |
| `config storage move NAME DESTINATION` | Storage apps | Yes | Move data and then update the registry. |
| `config storage remove NAME` | Storage apps | Yes | Remove one registry entry without deleting data. |

A storage-free declaration does not mount the host-level `--storage` option or
any `config storage ...` commands and does not accept `--scope storage`.

## Doctor statuses

| Status | Meaning |
| --- | --- |
| `runnable` | The selected runtime inputs are usable. |
| `env_not_set` | A storage app has no selected name. |
| `storage_not_ready` | The selected root or storage dotenv is not ready. |
| `user_dotenv_not_ready` | The fixed user dotenv is missing or unreadable. |
| `storage_registry_not_ready` | The storage registry is missing, unreadable, or invalid. |

Machine-readable diagnostics use file-specific keys including
`storage_enabled`, `apprc_dir`, `user_dotenv`, `apprc_toml`,
`selected_storage`, `selected_storage_root`, and `selected_storage_dotenv`.

## Dependency surfaces

The base package includes `python-dotenv`, `typed-settings`, `rich`, and
`typer`. It does not depend on `platformdirs`. Install `apprc[tui]` for
Textual. Development tools are in the `dev` dependency group; the package
works without `uv`.

## Documentation assets

Diagram source scripts and generated SVG files live together in
[`docs/assets`](assets). Edit the Python source and regenerate the matching SVG
instead of editing SVG output by hand.
