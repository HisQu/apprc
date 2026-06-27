# `apprc`: Application Runtime Config

`apprc` is a Python library for typed, env-backed application configuration. It
gives an app packaged defaults, optional app-wide dotenv config, optional
storage dotenv config, optional named storage roots, a generated Typer `config`
CLI, and a Textual editor.

## Table Of Contents

1. [Installation](#installation)
2. [Mental Model](#mental-model)
3. [Developer API](#developer-api)
4. [Runtime Precedence](#runtime-precedence)
5. [Generated CLI](#generated-cli)
6. [Upgrade Paths](#upgrade-paths)
7. [Filenames And Env Vars](#filenames-and-env-vars)
8. [Development](#development)

## Installation

```shell
python -m pip install apprc
```

Install optional structured logging support when the app calls
`setup_logging()`:

```shell
python -m pip install "apprc[logging]"
```

## Mental Model

AppRC now uses explicit persistence capability layers.

| Layer | File or selector | Writes by default? |
| --- | --- | --- |
| Packaged shared defaults | package `.env.shared` | never |
| Shell / explicit env files | `os.environ`, `--env-file` | never |
| App-wide config | platform config home `.env.apprc-app` | only `config app init`, `config setup` for app-wide constructors, or explicit app-scope saves |
| Storage config | `<storage-root>/.env.apprc-storage` | only `config setup`, `config storage add`, or explicit storage-scope saves |
| Named-storage index | `<app>.apprc.toml` | only `config storage add/remove` |

Runtime reads and diagnostics are zero-write. `config paths`, `config doctor`,
normal bootstrap, and opening the editor do not create files.

> [!IMPORTANT]
> AppRC no longer reads `.env.global` or `.env.local`. `config doctor` warns
> when those legacy files are found and tells users to move values to
> `.env.apprc-app` or `.env.apprc-storage`.

## Developer API

Declare config fields with `EnvConfig`, then choose one constructor.

```python
from pathlib import Path

from apprc import AppConfigKit, EnvConfig, env_field, env_owner


@env_owner(
    key="app",
    title="App",
    env_prefix="MYAPP_",
    rc_path=("app",),
)
class MyAppEnv(EnvConfig):
    storage_root: Path = env_field("STORAGE", editable=False, required=True)
    profile: str = env_field("PROFILE", default="default")


APP_CONFIG = AppConfigKit.storage_only(
    app_name="myapp",
    display_name="My App",
    config_package="myapp.config",
    envs=(MyAppEnv,),
)
```

| Constructor | Storage layer | App-wide layer | Named-storage index |
| --- | --- | --- | --- |
| `AppConfigKit.env_only(...)` | disabled | optional | disabled |
| `AppConfigKit.storage_only(...)` | required | optional | optional |
| `AppConfigKit.app_wide_config(...)` | disabled | default | disabled |
| `AppConfigKit.app_wide_storage(...)` | required | default | optional |

Use `storage_env_key="MYAPP_STORAGE"` only with storage-capable constructors.
Passing `storage_mode=` is removed and raises `TypeError`.

Public dotenv helpers use neutral env-file names:

- `EnvFileUpdate`
- `read_env_file(path)` / `write_env_file(path, values, owners=...)`
- `ensure_env_file(path)`
- `set_env_file_value(...)` / `clear_env_file_value(...)`
- `storage_env_path(root)`, `ensure_storage_env_file(root)`,
  `set_storage_env_value(...)`, and `clear_storage_env_value(...)`

The old `LocalEnvUpdate`, `read_local_env`, `write_local_env`,
`local_env_path`, `set_local_env_value`, and `clear_local_env_value` names are
removed.

Mount the generated config CLI:

```python
config_app = APP_CONFIG.typer_app(state_type=MyCliState)
app.add_typer(config_app, name="config")
```

## Runtime Precedence

When dotenv layers are loaded, values are merged in this order:

1. packaged `.env.shared`
2. app-wide `.env.apprc-app`, only when the layer is allowed and the file exists
3. selected storage `.env.apprc-storage`, only when storage is selected and the file exists
4. explicit `--env-file` values
5. existing `os.environ`

With `--env-file-overrides-os-environ`, explicit env files move after
`os.environ` and win over shell exports.

Storage selector resolution uses:

1. root `--storage`
2. shell env, for example `MYAPP_STORAGE`
3. explicit env files, respecting `--env-file-overrides-os-environ`
4. app-wide `.env.apprc-app`, when active
5. packaged `.env.shared`

Named selectors resolve through `<app>.apprc.toml` only when named storage is
allowed and the index file exists. Path selectors work without an index file and
ignore corrupt optional indexes at runtime; `config doctor` reports those stray
index problems as warnings. Bare selectors need the index when it exists, so a
corrupt index is fatal for named-selector resolution.

## Generated CLI

All commands below are shown with `myapp` as the application command name.

```shell
myapp config paths
myapp config doctor
myapp config show
myapp config setup
myapp config set KEY VALUE --scope app
myapp config set KEY VALUE --scope storage
myapp config edit

myapp config app init

myapp config storage add NAME PATH
myapp config storage list
myapp config storage remove NAME
```

Removed commands:

- `myapp config init`
- `myapp config list`

Use `myapp config storage add NAME PATH` and
`myapp config storage list` instead.

### `config paths`

`config paths` is always zero-write. It reports declared capabilities, active
layers, candidate paths, existing files, selected storage, named-storage index
status, and `writes: none`.

### `config setup`

`config setup` follows the constructor:

| Constructor | Setup behavior |
| --- | --- |
| `env_only` | prints env guidance; writes nothing |
| `storage_only` | asks for or accepts `--storage-root`; creates `.env.apprc-storage`; prints `export MYAPP_STORAGE=...` |
| `app_wide_config` | creates `.env.apprc-app` |
| `app_wide_storage` | creates `.env.apprc-app` and selected storage `.env.apprc-storage` |

Optional upgrades are separate commands, not setup prompts.

### `config set`

`config set` writes to app-wide or storage dotenv files.

- If exactly one writable layer is active, `--scope` may be omitted.
- If app-wide and storage are both active, pass `--scope app` or
  `--scope storage`.
- Env-only apps have no writable scope until an app-wide file is explicitly
  initialized with `config app init`.

`config set` skips runtime bootstrap so `--scope app` does not require storage
readiness. Storage is resolved only for `--scope storage` or when scope
inference needs to know whether storage is writable.

### `config edit`

`config edit` is the primary interactive view. It opens without creating files
and shows source columns for `Effective`, `Shell`, `App-wide`, `Storage`,
`Default`, and `Explanation`.

- The app-wide column appears when the app-wide layer is default-active or when
  `.env.apprc-app` exists.
- The storage column appears when a storage root is selected; a missing
  `.env.apprc-storage` is shown as empty until the user saves to storage.
- Saving chooses `app` or `storage` when both are writable, and creates only the
  selected target file.
- Named-storage controls are available only when named storage is enabled and an
  index is loaded; direct path-selected storage editing works without an index.

## Upgrade Paths

Storage-only users can start with one env var:

```shell
export MYAPP_STORAGE="/absolute/path/to/storage"
```

That path selector does not require a named-storage index.

To add app-wide config later:

```shell
myapp config app init
myapp config set app.profile work --scope app
```

To add named storages later:

```shell
myapp config storage add alpha /absolute/path/to/alpha
myapp config storage add beta /absolute/path/to/beta
export MYAPP_STORAGE="alpha"
```

`MYAPP_APPRC_TOML` only relocates the named-storage index. It is not required
for the default `<config-home>/<app>.apprc.toml` path.

## Filenames And Env Vars

| Purpose | Default |
| --- | --- |
| Packaged shared dotenv | `.env.shared` |
| App-wide dotenv | `.env.apprc-app` |
| Storage dotenv | `.env.apprc-storage` |
| Named-storage index | `<app>.apprc.toml` |
| Storage selector env key | derived as `<APP>_STORAGE` |
| Index relocation env key | derived as `<APP>_APPRC_TOML` |

Filename-style constructor inputs accept basenames only:

- `index_filename`
- `shared_env_filename`
- `app_wide_env_filename`
- `storage_env_filename`

## Development

```shell
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
```
