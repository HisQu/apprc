# AppRC Example Apps

This dev-only package contains four self-contained application examples plus
two utilities for manual and automated testing.

## Install From This Checkout

Run this at the AppRC repository root:

```bash
python -m pip install -e ".[tui]" -e examples/example_apps --no-build-isolation
```

This installs the local AppRC source, its Textual editor, and the example
console scripts. It does not require `uv` or `direnv`.

## Example Inventory

| Source | CLI | Storage | Focus |
|---|---|---:|---|
| [`config_only`](src/config_only/README.md) | `apprc-config-only` | No | Minimal `AppRC` declaration and user-wide dotenv values. |
| [`config_with_storage`](src/config_with_storage/README.md) | `apprc-config-with-storage` | Yes | Named storage, path selection, and storage-local values. |
| [`explicit_env_precedence`](src/explicit_env_precedence/README.md) | `apprc-explicit-env-precedence` | Yes | Shell values versus explicit dotenv files. |
| [`cli_runtime`](src/cli_runtime/README.md) | `apprc-cli-runtime` | Yes | App-owned callback and `CliRuntime`. |

Each application exposes a realistic `run` command and generated AppRC
configuration commands. The application packages do not import
`_example_apps_utils`; they can be copied independently.

## Disposable Manual Sessions

Open one example at a time:

```bash
apprc-examples-lab config-only
apprc-examples-lab config-with-storage
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
```

The lab opens the current user's shell, points the chosen app's
`<APP>_APPRC_DIR` at a fresh temporary directory, and prints a walkthrough.
No AppRC files exist when the shell opens. The temporary root is deleted when
the shell exits, including after an interruption or command failure.

> [!WARNING]
> A storage path that you explicitly choose outside the printed lab root is
> not lab-owned and is not deleted.

Directly running `apprc-config-*`, `apprc-explicit-env-precedence`, or
`apprc-cli-runtime` is intentionally realistic: those commands can create
persistent files at the selected paths. Use `config paths` first and inspect
`config purge --dry-run` before removing files.

## Command Availability

| Surface | Config only | Storage examples | CLI runtime |
|---|---:|---:|---:|
| `run` | Yes | Yes | Yes |
| Root env-file and logging options | Yes | Yes | Yes |
| Root `--storage NAME_OR_PATH` | No | Yes | Yes |
| `config paths/setup/doctor/show/set/edit/migrate/purge` | Yes | Yes | Yes |
| `config storage add/list/select/rename/repoint/move/remove` | No | Yes | Yes |
| App-owned `status`, `--workspace`, `--model`, `--dry-run` | No | No | Yes |

`storage examples` includes `config_with_storage` and
`explicit_env_precedence`.

## Automated Smoke Run

```bash
apprc-examples-run-all
```

The runner invokes the installed CLIs as subprocesses. It exercises setup,
doctor, application runtime, and purge for all four apps. Its precedence
scenario creates distinct shell-selected and explicit-file-selected storage
roots and values, then verifies both outcomes. Every scenario uses temporary
state and the command prints one JSON summary.

The pytest suite additionally covers the shared command surface on every app,
the full named-storage lifecycle on `config_with_storage`, selector names and
paths, `CliRuntime` runtime skipping, headless editor launch, and lab cleanup.

## Source Layout

Every application owns `config/app.py`, `config/sections/`,
`config/bundle.py`, `config/catalog.py`, and packaged
`config/apprc.defaults.env`. `_example_apps_utils` owns only the lab, registry,
and smoke runner.

## Docs

- [Development example guide](../../docs/Development.md#example-apps)
- [Generated CLI reference](../../docs/References.md#generated-cli-commands)
- [System model](../../docs/Explanations.md#system-model)
