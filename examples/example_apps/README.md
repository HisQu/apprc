# AppRC Example Apps

This dev-only package contains six self-contained application examples plus
two utilities for manual and automated testing. Four examples cover every
combination of AppRC's user-dotenv and storage capabilities; two cover advanced
CLI behavior.

## Install From This Checkout

Run this at the AppRC repository root:

```bash
python -m pip install -e ".[tui]" -e examples/example_apps --no-build-isolation
```

This installs the local AppRC source, its Textual editor, and the example
console scripts. It does not require `uv` or `direnv`.

## Example Inventory

| Source | CLI | User dotenv | Storage | Focus |
|---|---|---:|---:|---|
| [`process_env`](src/process_env/README.md) | `apprc-process-env` | No | No | Process environment and Python defaults; no managed user files. |
| [`user_dotenv`](src/user_dotenv/README.md) | `apprc-user-dotenv` | Yes | No | One managed `apprc.user.env`. |
| [`storage`](src/storage/README.md) | `apprc-storage` | No | Yes | Registry and storage-local values without a user dotenv. |
| [`user_dotenv_with_storage`](src/user_dotenv_with_storage/README.md) | `apprc-user-dotenv-with-storage` | Yes | Yes | Both persistent capabilities and both write scopes. |
| [`explicit_env_precedence`](src/explicit_env_precedence/README.md) | `apprc-explicit-env-precedence` | Yes | Yes | Process values versus explicit dotenv files. |
| [`cli_runtime`](src/cli_runtime/README.md) | `apprc-cli-runtime` | Yes | Yes | App-owned callback and `CliRuntime`. |

Each application exposes a realistic `run` command and generated AppRC
configuration commands. The application packages do not import
`_example_apps_utils`; they can be copied independently.

## Disposable Manual Sessions

Open one example at a time:

```bash
apprc-examples-lab process-env
apprc-examples-lab user-dotenv
apprc-examples-lab storage
apprc-examples-lab user-dotenv-with-storage
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
```

The lab opens the current user's shell and prints a walkthrough. For apps with
managed files, it points `<APP>_APPRC_DIR` at a fresh temporary directory. No
AppRC files exist when the shell opens. The temporary root is deleted when the
shell exits, including after an interruption or command failure.

> [!WARNING]
> A storage path that you explicitly choose outside the printed lab root is
> not lab-owned and is not deleted.

Directly running an example is intentionally realistic: commands with declared
managed features can create persistent files at the selected paths. Use
`config paths` first and inspect `config purge --dry-run` before removal.

## Command Availability

| Surface | Process env | User dotenv | Storage | Both |
|---|---:|---:|---:|---:|
| `run` | Yes | Yes | Yes | Yes |
| Root env-file and logging options | Yes | Yes | Yes | Yes |
| Root `--storage NAME_OR_PATH` | No | No | Yes | Yes |
| `config paths/show/doctor/purge` | Yes | Yes | Yes | Yes |
| `config setup/set/edit/migrate` | No | Yes | Yes | Yes |
| User write scope | No | Yes | No | Yes |
| Storage write scope and `config storage ...` | No | No | Yes | Yes |

The advanced examples declare both capabilities. `cli_runtime` also exposes
app-owned `status`, `--workspace`, `--model`, and `--dry-run` behavior.

All six examples use the backward-compatible required defaults. An application
with storage-backed commands and storage-free core commands can instead
declare `rc.Storage(required=False)`, then set `storage_required=True` only on
the `CliRuntime` that owns the storage-backed commands. The capability remains
visible in the same generated config interface.

## Automated Smoke Run

```bash
apprc-examples-run-all
```

The runner invokes the installed CLIs as subprocesses. It exercises setup,
doctor, application runtime, and purge for all six apps. Its precedence
scenario creates distinct shell-selected and explicit-file-selected storage
roots and values, then verifies both outcomes. Every scenario uses temporary
state and the command prints one JSON summary.

The pytest suite additionally covers the shared command surface on every app,
the full named-storage lifecycle on `storage`, selector names and
paths, `CliRuntime` runtime skipping, headless editor launch, and lab cleanup.

## Source Layout

Every application owns its declaration, config sections, bundle, and CLI.
Advanced examples retain the full lazy-facade package layout. Packaged
`apprc.defaults.env` is optional. `_example_apps_utils` owns only the lab,
registry, and smoke runner.

## Docs

- [Development example guide](../../docs/Development.md#example-apps)
- [Generated CLI reference](../../docs/References.md#generated-cli-commands)
- [System model](../../docs/Explanations.md#system-model)
