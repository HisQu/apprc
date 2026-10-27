# AppRC Example Apps

This dev-only package contains eight self-contained application examples plus
two utilities for manual and automated testing. Four examples cover combinations
of AppRC's user-dotenv and workspace capabilities, two demonstrate independent
path and process-environment choices, one covers advanced CLI behavior, and one
shows an importable client.

## Install From This Checkout

Run this at the AppRC repository root:

```bash
python -m pip install -e . -e src/apprc_dev/packaging/terminal -e examples/example_apps
```

This installs the local AppRC source, its Textual editor, and the example
console scripts. It does not require `uv` or `direnv`.

## Example Inventory

| Source | CLI | User dotenv | Workspace | Focus |
|---|---|---:|---:|---|
| [`process_env`](src/process_env/README.md) | `apprc-process-env` | No | No | Process environment and Python defaults; no managed user files. |
| [`user_dotenv`](src/user_dotenv/README.md) | `apprc-user-dotenv` | Yes | No | One managed `apprc.user.env`. |
| [`workspace`](src/workspace/README.md) | `apprc-workspace` | No | Yes | Registry and workspace-local values without a user dotenv. |
| [`cache_only`](src/cache_only/README.md) | `apprc-cache-only` | No | No | Cache path only; no config, schema, or workspace capability. |
| [`user_dotenv_with_workspace`](src/user_dotenv_with_workspace/README.md) | `apprc-user-dotenv-with-workspace` | Yes | Yes | Both persistent capabilities and both write scopes. |
| [`explicit_env_precedence`](src/explicit_env_precedence/README.md) | `apprc-explicit-env-precedence` | Yes | Yes | Process values versus explicit dotenv files. |
| [`cli_runtime`](src/cli_runtime/README.md) | `apprc-cli-runtime` | Yes | Yes | App-owned callback and `CliRuntime`. |
| [`library_client`](src/library_client/README.md) | `apprc-library-client` | Yes | No | An importable client loads its own settings. |

Each application exposes its declared AppRC groups and a realistic `run`
command where settings are declared. The application packages do not import
`_example_apps_utils`; they can be copied independently.

## Disposable Manual Sessions

Open one example at a time:

```bash
apprc-examples-lab process-env
apprc-examples-lab user-dotenv
apprc-examples-lab workspace
apprc-examples-lab cache-only
apprc-examples-lab user-dotenv-with-workspace
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
apprc-examples-lab library-client
```

The lab opens the current user's shell and points the app's declared root
environment key at a fresh temporary directory. No AppRC files exist when the
shell opens. The temporary root is deleted when the shell exits, including
after an interruption or command failure.

> [!WARNING]
> A workspace path that you explicitly choose outside the printed lab root is
> not lab-owned and is not deleted.

Directly running an example is intentionally realistic: commands with declared
managed features can create persistent files at the selected paths. Use
`paths` and `purge --all --dry-run` to inspect cleanup scope before removal.
The grouped `config`, `appdata`, `cache`, and `workspace` commands appear only
when the matching capability is declared.

## Command Availability

| Surface | Process env | User dotenv | Workspace | Cache only |
|---|---:|---:|---:|---:|
| Grouped `--help` | Yes | Yes | Yes | Yes |
| Root env-file and logging options | Yes | Yes | Yes | Yes |
| Root `--workspace NAME_OR_PATH` | No | No | Yes | No |
| `config` group | Yes | Yes | Yes | No |
| `appdata` group | No | No | No | No |
| `workspace` group | No | No | Yes | No |
| `cache` group | No | No | No | Yes |

The advanced `cli_runtime` example also exposes app-owned `status`, `--workdir`,
`--model`, and `--dry-run` behavior.

## Automated Smoke Run

```bash
apprc-examples-run-all
```

The runner invokes the installed CLIs as subprocesses. It exercises grouped
help, path initialization, runtime commands, and managed-resource cleanup for
all eight apps. Its precedence scenario creates distinct shell-selected and
explicit-file-selected workspace roots and values, then verifies both outcomes.
Every scenario uses temporary state and the command prints one JSON summary.

The pytest suite additionally covers registry discovery, the complete installed
CLI smoke run, `CliRuntime` behavior, headless editor launch, and lab cleanup.

## Source Layout

Every application owns its declaration, config sections, bundle, and CLI.
Imports use the declaration and bundle modules directly; there are no config catalogs or lazy config facades. Packaged
`apprc.defaults.env` is optional. `_example_apps_utils` owns only the lab,
registry, and smoke runner.

## Docs

The [complete setups](../../docs/EXAMPLES.md#choose-a-setup) explain which app to
choose. Each app uses the grouped [application CLI](../../docs/Explanations.md#application-cli),
whose [commands](../../docs/References.md#terminal-commands) are checked by the
[development checks](../../docs/Development.md#checks). Managed-resource cleanup
uses the [cleanup policy and confirmation flow](../../docs/How-To-User-Guides.md#preview-and-apply-a-purge).
The cache-only commands demonstrate the independent cache path without a config
directory or schema. Cleanup removes AppRC-managed files and internal resource
trees while retaining external workspace payloads.
