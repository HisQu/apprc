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

Declare user dotenv and storage support independently.

| Application | Declaration | Normal managed files | Structural environment variables |
| --- | --- | --- | --- |
| Process environment only | `rc.AppRC(...)` | None | None |
| User dotenv only | `rc.AppRC(..., user_dotenv=rc.UserDotenv())` | `~/.local/share/<app-id>/apprc.user.env` | `<APP>_APPRC_DIR` only when relocating it |
| Storage only | `rc.AppRC(..., storage=rc.Storage())` | `apprc.toml`, `storage/apprc.storage.env` | `<APP>_APPRC_DIR` for relocation; `<APP>_STORAGE=NAME_OR_PATH` only to override `selected_storage` |
| User dotenv and storage | Both arguments | `apprc.user.env`, `apprc.toml`, `storage/apprc.storage.env` | Both structural variables have the same roles |

Application setting variables such as `MYAPP_PROFILE` are separate from these
structural variables. The application declares them with `rc.field(...)`.

The declarations above are required by default. To let core commands run
without setup while keeping persistence available, mark the capabilities
optional:

```python
MyRC = rc.AppRC(
    app_id="myapp",
    display_name="My App",
    config_package="myapp.config",
    user_dotenv=rc.UserDotenv(required=False),
    storage=rc.Storage(required=False),
)
```

Then require storage only where it is actually used:

```python
runtime = rc.cli.CliRuntime(MyRC.kit, storage_required=True)
```

The strict runtime opens first-use setup in an interactive terminal. In a
script or pipeline it fails without writing and prints
`myapp config setup --yes`. Other runtimes can use the declaration default and
start without managed files.

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
  --user-dotenv \
  --storage \
  --target src
```

Omit `--user-dotenv` or `--storage` when the application does not need that
feature. AppRC derives
`MYAPP_STORAGE`; pass `--storage-selector-env-key` only to override it.

```python
from dataclasses import dataclass, field
from pathlib import Path

import apprc as rc


MyRC = rc.AppRC(
    app_id="myapp",
    display_name="My App",
    config_package="myapp.config",
    command_name="myapp",
    user_dotenv=rc.UserDotenv(),
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
@dataclass(kw_only=True)
class MyAppConfig:
    app: AppSettings = field(default_factory=AppSettings)
```

Optionally put non-secret defaults in `myapp/config/apprc.defaults.env`, mount the
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
application then owns any explicit setup step. Optional capabilities need no
setup until a command requires them or the user chooses to enable them.

For a user-dotenv-only app:

```bash
python -m pip install myapp
myapp config paths
myapp config setup --yes
myapp config doctor
```

Setup creates an empty `~/.local/share/myapp/apprc.user.env`. Until setup has
created it, `config set --scope user` and user-scoped editor writes are
disabled. A process-environment-only app has no setup command because it owns
no user files.

For a storage app:

```bash
python -m pip install myapp
myapp config paths
myapp config setup
myapp config doctor
```

Interactive setup first asks for the AppRC directory, with path completion,
then asks for the storage root. The suggested storage root is
`~/.local/share/myapp/storage/`. To provide either path directly or run
non-interactively:

```bash
myapp config setup \
  --apprc-dir /absolute/path/to/apprc \
  --storage-root /absolute/path/to/storage
myapp config setup --yes
```

Storage setup normally registers the initial root under the name `default`,
selects it in `apprc.toml`, and creates `apprc.storage.env` inside the root. If
the registry is empty and a bare `<APP>_STORAGE` value is present, setup uses
that requested name instead. It creates
`apprc.user.env` only when `rc.UserDotenv()` is also declared. It does not write
`MYAPP_STORAGE` to a dotenv file. A normal run uses `selected_storage`; export
`MYAPP_STORAGE=NAME_OR_PATH` only for a run-level selection override.

`--apprc-dir` affects the setup command's process only. When it differs from
the currently resolved directory, setup prints copyable commands for POSIX,
PowerShell, and `cmd.exe` that persist `<APP>_APPRC_DIR` for future runs.

The path form must point to an existing directory containing a readable
`apprc.storage.env`. AppRC logs whether it matched a registered name. If it is
unregistered, an interactive CLI offers to register it; declining uses it for
that process only. Non-interactive commands use it once without changing
`apprc.toml`.

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
`config edit` calls the registry-only operation **Reconnect** and keeps
**Move** for filesystem relocation.

New `add` and `repoint` operations reject a root already owned by another
name. Older duplicate aliases remain readable; `config doctor` warns, and a
direct path matching several aliases runs without choosing an arbitrary name.

## Edit dotenv values

Use `user` and `storage` because those are dotenv scopes, not generic config
categories:

```bash
myapp config set MYAPP_PROFILE development --scope user
myapp config set MYAPP_TOKEN secret-value --scope storage
myapp config edit
```

AppRC preserves unrelated dotenv text during `config set` and editor saves.
When one key has several active assignments, AppRC keeps the first assignment,
comments out the later ones, and reports their line numbers. The interactive
CLI and editor require confirmation before making that change. Non-interactive
commands print the warning after the write.

A user-dotenv-only declaration exposes only the user scope. A storage-only
declaration exposes only the storage scope. A process-environment-only
declaration exposes neither and has no `config set` or `config edit`. Missing
declared files require setup before writes. Old files on disk never enable a
scope or command that Python code did not declare.

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

If the active environment contains a bare name that is not registered,
migration does not guess whether an existing entry should be renamed. In an
interactive terminal it asks for the existing directory with path completion,
then offers to add the name or replace one old entry. For automation, provide
the decision explicitly:

```bash
# Add the missing name and keep all existing entries.
myapp config migrate --storage-root /existing/ontology --yes

# Rename and repoint one old entry; no application data is moved or deleted.
myapp config migrate \
  --storage-root /existing/ontology \
  --replace-storage old-name \
  --yes
```

`--yes` accepts a complete decision; it never selects an entry to replace.
When the chosen directory has no `apprc.storage.env`, migration creates the
empty marker so the result can bootstrap immediately.

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
| `storage_not_selected` | A storage app has no selected name or path. | Run setup, `storage select`, or pass a name or path. |
| `storage_not_ready` | The selector is invalid, a registered root is missing, or the storage dotenv is missing. | Fix or unset the selector; reconnect a manually moved registered root; run setup only for a missing marker. |
| `user_dotenv_not_ready` | `apprc.user.env` is missing or unreadable. | Run setup or fix permissions. |
| `storage_registry_not_ready` | `apprc.toml` is missing, unreadable, or invalid. | Run setup if it is absent; fix it if it is unreadable or invalid. |

For a declaration without storage, doctor reports stale `apprc.toml` as a
warning only. For one without `rc.UserDotenv()`, it does the same for a stale
`apprc.user.env`. Unsupported paths are `null` in the JSON payload.
`config edit` still opens when a declared file or storage selection is invalid.
For an invalid override it reports whether `--storage`, the process
environment, an explicit dotenv, or `apprc.toml` supplied the value. It keeps
valid registry entries usable and does not present Setup as a selector repair.
For a missing registered directory, select the entry and use **Reconnect**.
Setup remains available when AppRC can initialize a missing declared dotenv or
storage marker.
