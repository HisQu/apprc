# AppRC How-To Guides

## Table of contents

1. [Choose a declaration](#choose-a-declaration)
2. [Integrate AppRC](#integrate-apprc)
3. [Install and set up an AppRC app](#install-and-set-up-an-apprc-app)
4. [Manage storages](#manage-storages)
5. [Edit dotenv values](#edit-dotenv-values)
6. [Migrate from 0.19](#migrate-from-019)
7. [Remove user files](#remove-user-files)
8. [Troubleshoot `config doctor`](#troubleshoot-config-doctor)

## Choose a declaration

AppRC always uses one user dotenv. Add `rc.Storage()` only when the application
needs persistent user data.

| Application | Declaration | Normal files below `~/.local/share/<app-id>/` | Structural environment variables |
| --- | --- | --- | --- |
| No storage | `rc.AppRC(...)` | `apprc.user.env` | `<APP>_APPRC_DIR` only when relocating the AppRC directory |
| One storage | `rc.AppRC(..., storage=rc.Storage())` | `apprc.user.env`, `apprc.toml`, `storage/apprc.storage.env` | `<APP>_APPRC_DIR` for relocation; `<APP>_STORAGE=NAME` only to override `selected_storage` |
| Several storages | Same storage declaration | Same fixed files; extra storage roots are listed in `apprc.toml` | Same variables; storage names are registry data, not Python declarations |

Application setting variables such as `MYAPP_PROFILE` are separate from these
structural variables. The application declares them with `rc.field(...)`.

## Integrate AppRC

Install the runtime and optional editor:

```bash
python -m pip install apprc
python -m pip install "apprc[tui]"
```

Generate the recommended package layout:

```bash
apprc scaffold config \
  --package myapp \
  --app-id myapp \
  --display-name "My App" \
  --storage \
  --target src
```

Omit `--storage` for a storage-free application. AppRC derives
`MYAPP_STORAGE`; pass `--storage-selector-env-key` only to override it.

```python
from pathlib import Path

import apprc as rc


MyRC = rc.AppRC(
    app_id="myapp",
    display_name="My App",
    config_package="myapp.config",
    command_name="myapp",
    storage=rc.Storage(selector_env_key="MYAPP_STORAGE"),
)


@MyRC.config("app", prefix="MYAPP_", title="App")
class AppSettings(rc.Config):
    storage_root: Path = rc.field(
        "MYAPP_STORAGE",
        editable=False,
        required=True,
    )
    profile: str = rc.field("MYAPP_PROFILE", default="default")
    token: str = rc.field("MYAPP_TOKEN", required=True, secret=True)


@MyRC.bundle
class MyAppConfig:
    app: AppSettings
```

Put non-secret defaults in `myapp/config/apprc.defaults.env`, mount the
generated commands, and construct config only after AppRC prepares the CLI
runtime:

```python
import typer

from myapp.config import MyAppConfig, MyRC


app = typer.Typer()
MyRC.mount_cli(app)


@app.command()
def run() -> None:
    cfg = MyAppConfig()
    typer.echo(cfg.app.profile)
```

For a non-Typer entrypoint, call `MyRC.bootstrap()` first. Libraries should
accept an already constructed config object instead of choosing the caller's
storage or dotenv policy.

## Install and set up an AppRC app

Installing the Python package installs only code and packaged defaults. The
application then owns an explicit setup step.

For a storage-free app:

```bash
python -m pip install myapp
myapp config paths
myapp config setup --yes
myapp config doctor
```

Setup creates an empty `~/.local/share/myapp/apprc.user.env` so the file model
does not gain a separate “user dotenv absent” state.

For a storage app:

```bash
python -m pip install myapp
myapp config paths
myapp config setup
myapp config doctor
```

Interactive setup shows the proposed root
`~/.local/share/myapp/storage/` before creating it. To choose another root with
shell completion or to run non-interactively:

```bash
myapp config setup --storage-root /absolute/path/to/storage
myapp config setup --yes
```

Storage setup creates the user dotenv, registers the initial root under the
name `default`, selects it in `apprc.toml`, and creates
`apprc.storage.env` inside the root. It does not write `MYAPP_STORAGE` to a
dotenv file. A normal run uses `selected_storage`; export
`MYAPP_STORAGE=NAME` only for a run-level selection override.

## Manage storages

Every storage is a named registry entry, including the initial `default`
storage.

```bash
myapp config storage list
myapp config storage add project-a /data/project-a
myapp config storage select project-a
myapp config storage rename project-a primary
```

The first added storage becomes selected. Later additions preserve the current
selection. Renaming the selected storage updates the selection. Removing it
clears selection and warns.

Choose the operation that matches the intended filesystem change:

```bash
# Change only the root recorded in apprc.toml.
myapp config storage repoint primary /already/existing/data

# Move the complete directory, then update apprc.toml.
myapp config storage move primary /new/empty/destination

# Remove only the registry entry. Data remains.
myapp config storage remove primary
```

Relative roots resolve relative to `apprc.toml`, not the current directory.
`config edit` exposes the same supported operations.

## Edit dotenv values

Use `user` and `storage` because those are dotenv scopes, not generic config
categories:

```bash
myapp config set MYAPP_PROFILE development --scope user
myapp config set MYAPP_TOKEN secret-value --scope storage
myapp config edit
```

A storage-free declaration exposes only the user scope. It also hides
`--storage`, all `config storage ...` commands, and the editor's storage
section. An old `apprc.toml` on disk does not re-enable them.

## Migrate from 0.19

Update the application declaration, then inspect and apply the released-layout
migration:

```bash
myapp config migrate --dry-run
myapp config migrate --yes
```

| Released 0.19 source | 0.20 destination |
| --- | --- |
| package `.env.shared` | package `apprc.defaults.env` — app author changes source |
| `.env.apprc-app` | `<apprc-dir>/apprc.user.env` |
| `.env.apprc-storage` | `<storage-root>/apprc.storage.env` |
| `<app>.apprc.toml` or custom `<APP>_APPRC_TOML` | `<apprc-dir>/apprc.toml` |
| path-valued `<APP>_STORAGE` | `[storages.default].root` plus `selected_storage = "default"` |

Migration scans former Linux, macOS, and Windows platformdirs locations and
declared `legacy_app_ids`. It removes path selectors from the migrated user
dotenv and warns about exported structural variables that the process cannot
edit. It ignores `apprc.app.env` because no released AppRC version used that
name.

Conflicts stop the operation before changes. Existing destinations are never
replaced.

## Remove user files

Uninstalling a Python package does not remove user-created files. Run purge
while the application command is still installed:

```bash
myapp config purge --dry-run
myapp config purge --yes
python -m pip uninstall myapp
```

> [!CAUTION]
> Purge recursively deletes each registered storage root strictly inside the
> AppRC directory. Review `--dry-run` output before confirming.

Purge deletes only fixed AppRC files and registered internal roots. For a root
outside the AppRC directory, it deletes `apprc.storage.env` but retains the
root and all other files. It never recursively deletes the entire
`--apprc-dir`, never follows symlinks, and removes directories only when empty.
A malformed registry stops purge before any deletion.

## Troubleshoot `config doctor`

Start with read-only state:

```bash
myapp config paths
myapp config doctor
myapp config doctor --json
```

| Status | Meaning | Next action |
| --- | --- | --- |
| `runnable` | Required dotenv files and selected storage are usable. | Run the application. |
| `env_not_set` | A storage app has no selected registry name. | Run setup or `storage select`. |
| `storage_not_ready` | The selected root or storage dotenv is missing. | Correct the root or rerun setup. |
| `user_dotenv_not_ready` | `apprc.user.env` is missing or unreadable. | Run setup or fix permissions. |
| `storage_registry_not_ready` | `apprc.toml` is missing, unreadable, or invalid. | Run setup or fix the registry. |

For a storage-free declaration, doctor reports stale `apprc.toml` as a warning
only. The JSON payload uses file-specific keys such as `apprc_dir`,
`user_dotenv`, `apprc_toml`, and `storage_dotenv`.
