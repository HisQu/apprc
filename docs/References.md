# AppRC Reference

## Table of contents

1. [Public interfaces](#public-interfaces)
2. [Application declaration](#application-declaration)
3. [Configuration files](#configuration-files)
4. [Environment variables](#environment-variables)
5. [Runtime precedence](#runtime-precedence)
6. [Generated CLI commands](#generated-cli-commands)
7. [Doctor statuses](#doctor-statuses)
8. [Dependency surfaces](#dependency-surfaces)
9. [Documentation assets](#documentation-assets)

Use [How-To User Guides](How-To-User-Guides.md) for procedures and
[Explanations](Explanations.md) for design rationale.

## Public interfaces

Normal integrations use `import apprc as rc`.

| Name | Purpose |
| --- | --- |
| `rc.AppRC` | Declares one application, registers config, bootstraps runtime state, and mounts generated commands. |
| `rc.Storage` | Enables storage and declares its selector key, suggested root, first-run prompt policy, and dotenv filename. |
| `rc.Config` | Base for env-backed typed config. |
| `rc.ConfigBase` | Base for Python-only config. |
| `rc.field` | Declares one env-backed field with a full env key. |
| `rc.cli` | Advanced Typer runtime and mount helpers. |
| `rc.files` | Dotenv and managed-file helpers. |
| `rc.storage` | Storage registry, selector, path, and archive helpers. |
| `rc.provenance` | Runtime value-origin helpers. |
| `rc.schema` | Read-only config metadata. |

`rc.field(...)` accepts `default`, `default_factory`, `required`, `title`,
`description`, `editable`, `secret`, `choices`, and `packaged_default`.
`packaged_default` describes an intentional difference between the Python
fallback and `apprc.defaults.env`. The old `shared_default` spelling remains a
0.20 compatibility alias.

## Application declaration

```python
MyRC = rc.AppRC(
    app_name="myapp",
    config_package="myapp.config",
    display_name="My App",
    command_name="myapp",
    storage=rc.Storage(),
)
```

`AppRC` arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `app_name` | required | Stable name used for platform directories and derived env keys. |
| `config_package` | required | Import package containing `apprc.defaults.env`. |
| `display_name` | `app_name` | Label shown to users. |
| `command_name` | `app_name` | Executable shown in generated instructions. |
| `storage` | `None` | `rc.Storage(...)` when the application persists data. |
| `defaults_env_filename` | `apprc.defaults.env` | Packaged defaults basename. |
| `app_env_filename` | `apprc.app.env` | Per-user app dotenv basename. |
| `apprc_toml_filename` | `apprc.toml` | Storage registry and future AppRC metadata basename. |

`Storage` arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `env_key` | derived `<APP>_STORAGE` | Storage selector env key. |
| `suggested_root` | platform user data path | First setup suggestion. |
| `prompt_on_first_run` | `True` | Offer setup before an interactive runtime command. |
| `env_filename` | `apprc.storage.env` | Dotenv basename inside each storage. |

Filename arguments accept one basename, not a path. Use
`<APP>_APPRC_TOML` to relocate the TOML file.

The 0.19 constructors `env_only`, `storage_only`, `app_wide_config`, and
`app_wide_storage` emit `DeprecationWarning` in 0.20 and retain their old
filenames and setup behavior. They are removed in 0.21.

## Configuration files

| File | Location | Role |
| --- | --- | --- |
| `apprc.defaults.env` | `config_package` | Non-secret defaults shipped by the app. |
| `apprc.app.env` | `platformdirs.user_config_path(app_name, appauthor=False)` | Per-user overrides and persisted storage selector. |
| `apprc.storage.env` | Selected storage root | Storage-specific overrides. |
| `apprc.toml` | Platform config home | Named storage registry and future AppRC metadata. |

Current filenames win when current and legacy files both exist. AppRC does not
merge competing files. When only a legacy file exists, reads and writes stay
on that file until `config migrate` moves it.

| Legacy | Current |
| --- | --- |
| `.env.shared` | `apprc.defaults.env` |
| `.env.apprc-app` and `.env.global` | `apprc.app.env` |
| `.env.apprc-storage` and `.env.local` | `apprc.storage.env` |
| `<app>.apprc.toml` | `apprc.toml` |

The packaged defaults fallback is read-only. Rename that source file in the
application repository.

## Environment variables

For `app_name="myapp"`:

| Variable | Purpose |
| --- | --- |
| `MYAPP_STORAGE` | Direct storage path or name registered in `apprc.toml`. |
| `MYAPP_APPRC_TOML` | Optional explicit TOML path. |
| App-declared keys | Typed runtime settings such as `MYAPP_PROFILE`. |

## Runtime precedence

Later rows win unless noted:

| Order | Source |
| --- | --- |
| 1 | Packaged `apprc.defaults.env` |
| 2 | Per-user `apprc.app.env` |
| 3 | Selected storage `apprc.storage.env` |
| 4 | Explicit `--env-file` values, in argument order |
| 5 | Existing `os.environ` |

`--env-file-overrides-os-environ` swaps the last two precedence positions.

Storage selection checks `--storage`, shell or explicit env according to that
same override policy, `apprc.app.env`, then packaged defaults. A direct path
does not require `apprc.toml`. A bare registered name resolves through it.

Provenance emitted for dotenv values uses
`shell_dotenv_defaults`, `shell_dotenv_app`, `shell_dotenv_storage`, and
`shell_dotenv_explicit`.

## Generated CLI commands

| Command | Writes | Purpose |
| --- | --- | --- |
| `config paths [--json]` | No | Show declarations and selected paths. |
| `config doctor [--json]` | No | Diagnose readiness and give next steps. |
| `config show [--json]` | No | Show resolved runtime config. |
| `config setup [--storage-root PATH] [-y]` | Yes | Initialize the declared storage or explain that none is needed. |
| `config migrate [--dry-run] [-y]` | With neither `--dry-run` nor cancellation | Move legacy managed files after full preflight. |
| `config set KEY VALUE --scope app\|storage` | Yes | Validate and save one override. |
| `config edit` | Opening: no | Open the Textual editor; confirmed actions may write. |
| `config app init` | Yes | Create an empty `apprc.app.env`. |
| `config storage add NAME PATH` | Yes | Create or update one named storage. |
| `config storage list [--json]` | No | List registered storage roots. |
| `config storage remove NAME` | Yes | Remove one registry entry, not its directory. |

The TUI always shows `Setup`. Storage declarations also expose creation,
registration, rename, repoint, move, archive, and delete actions. Action
availability follows the current storage selection; the first storage does not
require a pre-existing TOML file.

Machine-readable diagnostics use the current vocabulary only:
`storage_enabled`, `app_config_enabled`, `named_storage_enabled`, `app_env`,
`storage_selector_env_key`, and `apprc_toml`.

## Doctor statuses

| Status | Meaning |
| --- | --- |
| `runnable` | The selected runtime inputs are usable. |
| `env_not_set` | Storage is enabled but no selector resolved. |
| `storage_not_ready` | The selected root or storage dotenv is not ready. |
| `app_config_not_ready` | A required legacy app config file is not ready. |
| `named_storage_not_ready` | AppRC TOML could not be read or parsed. |

## Dependency surfaces

The base package includes `platformdirs`, `python-dotenv`, `typed-settings`,
`rich`, and `typer`. Install `apprc[tui]` for Textual. Development tools are in
the `dev` dependency group; the package still works without `uv`.

## Documentation assets

Diagram sources and their generated SVG files live together in
[`docs/assets`](assets). Edit the Python source and run it to regenerate the
matching SVG. Do not hand-edit generated SVG output.
