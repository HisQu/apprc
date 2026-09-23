# Examples

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Development](Development.md)

- [Choose a setup](#choose-a-setup)
- [Run the example applications](#run-the-example-applications)
- [Settings without managed files](#settings-without-managed-files)
- [Persistent user preferences](#persistent-user-preferences)
- [Named storage without user overrides](#named-storage-without-user-overrides)
- [User settings and storage](#user-settings-and-storage)
- [Explicit dotenv precedence](#explicit-dotenv-precedence)
- [An application-owned CLI callback](#an-application-owned-cli-callback)
- [Several sections and temporary overrides](#several-sections-and-temporary-overrides)

## Choose a setup

Choose the files your application needs. [User dotenv](Explanations.md#user-dotenv-and-the-apprc-directory)
and [storage](Explanations.md#storage) are independent options on one `AppRC`
declaration; they are not different application classes.

| Setup | Saved user overrides | Named data directories | Choose it when |
| --- | --- | --- | --- |
| [Settings without managed files](#settings-without-managed-files) | No | No | The process environment and application defaults supply the settings. |
| [Persistent user preferences](#persistent-user-preferences) | Yes | No | Users need to save preferences, but the application does not manage data directories. |
| [Named storage without user overrides](#named-storage-without-user-overrides) | No | Yes | Settings belong to selected data directories. |
| [User settings and storage](#user-settings-and-storage) | Yes | Yes | User preferences apply across several data directories, with per-directory overrides. |
| [Explicit dotenv precedence](#explicit-dotenv-precedence) | Yes | Yes | Invocation files must supplement or override process inputs. |
| [An application-owned CLI callback](#an-application-owned-cli-callback) | Yes | Yes | The application has its own root CLI options and state. |
| [Several sections and temporary overrides](#several-sections-and-temporary-overrides) | No | No | Several parts of Python application code need related settings. |

The first four setups cover all combinations of the two optional file features.
The remaining examples demonstrate features that can be used with those setups.

## Run the example applications

From an AppRC checkout, install the code, terminal distribution, and examples:

```shell
python -m pip install -e . -e src/apprc_dev/packaging/terminal -e examples/example_apps
```

`apprc-examples-lab NAME` opens a disposable shell for one example. It removes
inherited example-specific variables and sets the correct AppRC directory to a
temporary location. Run each command sequence below inside the specified lab;
exit that shell before opening another. The shell starts in your original
working directory. The command sequences below first change into `$APPRC_EXAMPLE_LAB_ROOT`, so relative data paths stay
inside the temporary directory. On PowerShell use `cd $env:APPRC_EXAMPLE_LAB_ROOT`.

> [!IMPORTANT]
> Keep demonstration data inside the lab's printed temporary directory.
> Directories explicitly chosen elsewhere are not removed when the lab exits.

The [example package README](../examples/example_apps/README.md) describes the
lab and smoke runner. Each application has its own declaration, section, bundle,
and CLI. Those files can be copied without the lab utilities. The
[How-to user guides](How-To-User-Guides.md) provide smaller independent Python
programs when you do not need a CLI application.

## Settings without managed files

Choose this setup for a script or service configured by its launcher. This
complete `demo.py` uses no files:

<!-- example-file: demo.py -->
```python
import apprc as rc

MyRC = rc.AppRC(app_id="demo")

@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    timeout: int = rc.field("DEMO_TIMEOUT", default=30)

first = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
second = MyRC.resolve(environment={"DEMO_TIMEOUT": "20"})
assert first.build(ClientSettings).timeout == 10
assert second.build(ClientSettings).timeout == 20
assert MyRC.resolve(environment={}).build(ClientSettings).timeout == 30
print("separate runs: 10, 20; Python default: 30")
```

Run `python demo.py`. Each [`ResolvedConfig`](Explanations.md#resolvedconfig)
retains its own inputs. To use actual process values, omit `environment`.

The runnable [process_env declaration](../examples/example_apps/src/process_env/config/app.py)
adds a [CLI](../examples/example_apps/src/process_env/cli.py).
It declares neither user overrides nor storage:

```shell
apprc-examples-lab process-env
```

Inside the lab:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-process-env run
apprc-process-env config doctor
```

`run` prints the typed `profile` and `debug` values. There is no writable scope,
so setup and editing commands are absent. The
[packaged-defaults guide](How-To-User-Guides.md#ship-defaults-with-the-application)
shows how to add a defaults file if the application needs one.

## Persistent user preferences

The [user_dotenv declaration](../examples/example_apps/src/user_dotenv/config/app.py)
enables `user_dotenv=rc.UserDotenv()` on `AppRC`. Its
[settings section](../examples/example_apps/src/user_dotenv/config/sections/app.py)
defines a profile and a boolean debug setting. The user dotenv stores changes
outside the installed package.

```shell
apprc-examples-lab user-dotenv
```

Inside the lab:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-user-dotenv config setup --yes
apprc-user-dotenv config set app.profile personal --scope user
apprc-user-dotenv run
apprc-user-dotenv config edit
```

`run` reports profile `personal`. The edit is in `apprc.user.env` under the lab's
AppRC directory. The editor shows that layer and the Python defaults. The
[Python preference guide](How-To-User-Guides.md#save-a-user-preference)
performs the same setup and edit through `ConfigManager`.

## Named storage without user overrides

The [storage declaration](../examples/example_apps/src/storage/config/app.py)
enables `storage=rc.Storage()`. Each directory has its own configuration file.
The [settings section](../examples/example_apps/src/storage/config/sections/app.py)
requires a storage path and a secret API-token value.

```shell
apprc-examples-lab storage
```

Inside the lab, initialize a directory and supply a demonstration placeholder:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-storage config setup --yes --storage-root ./data
apprc-storage config set app.api_token example-placeholder --scope storage
apprc-storage config set app.profile work --scope storage
apprc-storage run
apprc-storage config storage list
```

`run` reports profile `work` and the selected root while redacting the token.
`apprc.toml` records the directory; `data/apprc.storage.env` contains the overrides.
The [data-directory guide](How-To-User-Guides.md#store-data-outside-the-source-checkout)
shows application code writing its own report inside a selected root. The
[storage operations reference](References.md#storage-operations) covers moving,
reconnecting, archiving, and unregistering directories.

## User settings and storage

The [combined declaration](../examples/example_apps/src/user_dotenv_with_storage/config/app.py)
enables both `UserDotenv()` and `Storage()`. A saved user preference applies
unless the selected storage or another higher-priority layer overrides it.

```shell
apprc-examples-lab user-dotenv-with-storage
```

Inside the lab:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-user-dotenv-with-storage config setup --yes --storage-root ./data
apprc-user-dotenv-with-storage config set app.api_token example-placeholder --scope user
apprc-user-dotenv-with-storage config set app.profile personal --scope user
apprc-user-dotenv-with-storage run
apprc-user-dotenv-with-storage config set app.profile work --scope storage
apprc-user-dotenv-with-storage run
```

The first run reports `personal`; the second reports `work`. Both saved values
still exist, but the storage layer wins. The
[config editor](Explanations.md#config-editor) displays both values, and the
[edit-removal guide](How-To-User-Guides.md#edit-or-remove-a-saved-override)
shows how removing an override reveals the lower-priority value again.

This setup is useful when different datasets need different endpoints or options
while sharing user preferences. [Storage selection](References.md#storage-selection)
chooses which directory's overrides participate.

## Explicit dotenv precedence

The [precedence application](../examples/example_apps/src/explicit_env_precedence/cli.py)
uses both persistent features and a `label` setting. It demonstrates the
[priority switch](References.md#source-precedence) between process values and
explicit dotenv files.

```shell
apprc-examples-lab explicit-env-precedence
```

Inside a POSIX lab shell:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-explicit-env-precedence config setup --yes --storage-root ./data
printf 'APPRC_EXAMPLE_PRECEDENCE_LABEL=file\n' > invocation.env
export APPRC_EXAMPLE_PRECEDENCE_LABEL=shell
apprc-explicit-env-precedence --env-file invocation.env run
apprc-explicit-env-precedence --env-file invocation.env --env-file-overrides-os-environ run
```

The first run reports `shell`; the second reports `file`. On PowerShell, write
the file with `Set-Content` and set `$env:APPRC_EXAMPLE_PRECEDENCE_LABEL` instead.
The [independent Python guide](How-To-User-Guides.md#load-dotenv-files)
reproduces the priority change without shell-specific commands.

## An application-owned CLI callback

The [cli_runtime application](../examples/example_apps/src/cli_runtime/cli.py)
defines its own `RuntimeOptions` and `RuntimeState`. Its root callback passes
options to `rc.cli.CliRuntime.prepare()`. The resulting state contains both
AppRC's `ResolvedConfig` and the application's `workspace`, `model`, and
`dry_run` values.

```shell
apprc-examples-lab cli-runtime
```

Inside the lab:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-cli-runtime status
apprc-cli-runtime config setup --yes --storage-root ./data
apprc-cli-runtime config set runtime.api_token example-placeholder --scope storage
apprc-cli-runtime --workspace ./workspace --model example-model --dry-run run
```

`status` works before setup. `run` prints the app-owned options and resolved
settings together. `CliRuntime.mount_config_group()` supplies the configuration
commands without replacing the application's root callback. The ordinary
[Typer mounting guide](How-To-User-Guides.md#add-configuration-commands-to-typer)
is smaller when the application does not need a custom callback.

## Several sections and temporary overrides

The complete [section_bundle.py](../examples/section_bundle.py) defines an API
client section and an output section, registers their
[config bundle](Explanations.md#config-bundles), and passes it to application code.
It supplies explicit environment mappings, so it needs no setup or saved files.

From the repository root:

```shell
python examples/section_bundle.py
```

Expected output:

```text
json: timeout=10
one request: timeout=5
json: timeout=20
```

The first line uses a bundle built from `DEMO_TIMEOUT=10`. The second uses a
scoped copy for one operation. Reloading the original section produces the third
line while the scoped copy retains its own value. The initial `ResolvedConfig`
can still build a section with timeout `10`.

The [bundle guide](How-To-User-Guides.md#pass-several-settings-sections-together)
shows the declaration in full. The
[reload guide](How-To-User-Guides.md#reload-settings-or-use-temporary-overrides)
explains when explicit Python overrides survive a reload.
