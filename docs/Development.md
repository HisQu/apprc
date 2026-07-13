<!-- ======================================================== -->

<br>

## Table Of Contents
<!-- ======================================================== -->

1. [1. Development](#1-development)
2. [2. Maintainer Workflow](#2-maintainer-workflow)
   1. [Before Editing](#before-editing)
   2. [Repository Routing](#repository-routing)
   3. [Environment Setup](#environment-setup)
   4. [Example Apps](#example-apps)
   5. [Release Workflow](#release-workflow)
3. [3. Documentation Workflow](#3-documentation-workflow)
   1. [Documentation Rules](#documentation-rules)
   2. [README And PyPI README](#readme-and-pypi-readme)
   3. [Documentation Assets](#documentation-assets)
4. [4. Verification](#4-verification)
   1. [Docs Verification](#docs-verification)
   2. [Python Verification](#python-verification)
   3. [Review Checklist](#review-checklist)

<br>

# 1. Development

Use this file before changing AppRC itself. Use
[How-To User Guides](How-To-User-Guides.md) for adopter recipes,
[References](References.md) for exact public names, and
[Explanations](Explanations.md) for the system model.

<br>

# 2. Maintainer Workflow

<!-- ======================================================== -->

<br>

## Before Editing
<!-- ======================================================== -->

Start every non-trivial change by checking the current repo state:

```bash
git status --short
rg --files
```

Read the owner files for the behavior before editing. AppRC has many small
modules with deliberately narrow responsibilities; reuse existing helpers
before adding new ones.

Do not revert unrelated worktree changes. If generated docs or locks are
already modified, understand whether they are part of the requested task before
touching them.

<br>

<!-- ======================================================== -->

<br>

## Repository Routing
<!-- ======================================================== -->

Put changes where the repo already has an owner:

| Change Type | Owner |
|---|---|
| Developer-declared app specs, env config classes, owner metadata, and schema lookup | [src/apprc/definition](../src/apprc/definition) |
| Process-time dotenv bootstrap, provenance, and read-only diagnostics | [src/apprc/runtime](../src/apprc/runtime) |
| AppRC-managed config-home files, dotenv editing, setup flows, and storage roots | [src/apprc/user_files](../src/apprc/user_files) |
| Typer command integration, CLI presentation, and Textual TUI surfaces | [src/apprc/interfaces](../src/apprc/interfaces) |
| Broad AppRC utility helpers | [src/apprc/utils](../src/apprc/utils) |
| Public facade exports | [src/apprc/__init__.py](../src/apprc/__init__.py) and package `__init__.py` files |
| Example CLIs | [examples/example_apps](../examples/example_apps) |
| Example bootstrap helper | [src/apprc_dev/example_apps](../src/apprc_dev/example_apps) |
| Tests | [tests](../tests) |
| Documentation | [docs](.) and [README.md](../README.md) |
| PyPI README generation helper | [src/apprc_dev/packaging](../src/apprc_dev/packaging) |

Ask before creating a new top-level directory when one of these owners is a
reasonable fit.

<br>

<!-- ======================================================== -->

<br>

## Environment Setup
<!-- ======================================================== -->

The repo works without `uv`, but `uv`, `direnv`, and `just` are supported for
maintainer convenience.

Plain pip:

```bash
python -m pip install -e "." --group dev
```

Locked `uv` environment:

```bash
just sync
```

Use project-local tools when available:

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
```

Do not edit shell startup files or `$PATH` to make tools resolvable. If a tool
is missing, check whether the project environment is active and then try the
`.venv/bin/<tool>` path.

<br>

<!-- ======================================================== -->

<br>

## Example Apps
<!-- ======================================================== -->

The example package is a dev-only editable install at
[examples/example_apps](../examples/example_apps). It exposes one console
script per AppRC mode:

| Script | AppRC Surface |
|---|---|
| `apprc-env-only` | `rc.AppRC.env_only(...)` |
| `apprc-storage-only` | `rc.AppRC.storage_only(...)` |
| `apprc-app-wide-config` | `rc.AppRC.app_wide_config(...)` |
| `apprc-app-wide-storage` | `rc.AppRC.app_wide_storage(...)` |
| `apprc-explicit-env-precedence` | Explicit env-file selector precedence |
| `apprc-cli-runtime` | `CliRuntime` with an app-owned callback |
| `apprc-examples-run-all` | Compact non-interactive scenario runner |

The source tree intentionally uses one Python package per app so the examples
match what a downstream project should copy:

| Package | Purpose |
|---|---|
| `env_only` | Minimal env-only app with `config/`, `cli.py`, and packaged `config/.env.shared`. |
| `storage_only` | Storage-selected app with storage-local dotenv fields. |
| `app_wide_config` | Storage-free app that uses the app-wide dotenv layer. |
| `app_wide_storage` | App-wide defaults plus selected storage roots. |
| `explicit_env_precedence` | Storage selector precedence with explicit env files. |
| `cli_runtime` | Typer callback integration through `CliRuntime`. |
| `_example_apps_utils` | Shared scenario runner helpers; not a user app template. |

Generated files intentionally live outside this source tree under
`examples/example_app_disk_files/`. That ignored directory contains local
runtime state written by the bootstrap helper; do not import from it or copy it
as an application template.

Each app package owns its own `config/` package and points `config_package` at
that package. Do not reintroduce a shared config module for the examples; that
would teach the wrong integration shape.

The example config packages follow the standard AppRC app layout:

```text
<example>/config/
  __init__.py
  __init__.pyi
  _facade.py
  app.py
  sections/
    __init__.py
    __init__.pyi
    _facade.py
    app.py
  bundle.py
  catalog.py
  .env.shared
```

Simple sections stay as files under `sections/`. Larger sections become nested
packages under `sections/<section>/`; `cli_runtime` uses
`sections/runtime/` to exercise that layout. Do not create domain-specific
sibling packages next to `sections/` for config declarations. Package
`__init__.py` files should stay as lightweight facades, and bundles should
import section classes from concrete leaf modules.

New downstream apps can generate the same skeleton with:

```bash
apprc scaffold config \
  --package myapp \
  --mode storage-only \
  --app-name myapp \
  --display-name "My App" \
  --storage-env-key MYAPP_STORAGE \
  --target src
```

Install the example console scripts when the dev dependency group has not
already installed them:

```bash
python -m pip install -e examples/example_apps --no-build-isolation
```

Bootstrap all local example files before manual testing:

```bash
set -a; source .env.example_apps; set +a
python -m apprc_dev.example_apps.bootstrap --output-root "$APPRC_EXAMPLE_APPS_ROOT"
```

When direnv is enabled, `.envrc` sources `.env.example_apps` and runs the
bootstrap helper automatically after the project venv is active. Manual setup
uses the same `.env.example_apps` file and `APPRC_EXAMPLE_APPS_ROOT`.

This writes ignored files under `examples/example_app_disk_files/`:

| File | Purpose |
|---|---|
| `.apprc-example-*/.env` | Per-app arbitrary user env file. AppRC does not choose this location; source it manually or pass it with `--env-file` when path relocation is not needed. |
| `xdg-config-home/<app>/.env.apprc-app` | Shared generated app-wide dotenv layer. |
| `xdg-config-home/<app>/<app>.apprc.toml` | Shared generated named-storage index for storage-capable examples. |
| `.apprc-example-*/storages/alpha/.env.apprc-storage` | Storage-local dotenv layer. |

Every generated `.env` and `.toml` file starts with comments explaining the
AppRC layer and where that file would normally live in a real application.

Source one example environment when testing its console script:

```bash
set -a; source .env.example_apps; set +a
apprc-storage-only config paths
apprc-storage-only config doctor
apprc-storage-only config storage list
apprc-storage-only config show --json
```

Use the runtime example to inspect the app-owned callback path:

```bash
set -a; source .env.example_apps; set +a
apprc-cli-runtime --workspace /tmp/apprc-workspace --model demo status
apprc-cli-runtime --workspace /tmp/apprc-workspace --model demo run
apprc-cli-runtime config doctor
```

The test suite exercises every generated command for every example mode:
`config paths`, `config show`, `config doctor`, `config setup`, `config set`,
`config edit`, `config app init`, and all mounted `config storage` commands.
Storage-free modes also assert that storage commands are unavailable.

<br>

<!-- ======================================================== -->

<br>

## Release Workflow
<!-- ======================================================== -->

AppRC publishes from an annotated `vMAJOR.MINOR.PATCH` tag. A tag push runs the
complete CI matrix, builds and validates the wheel and source distribution,
waits for approval in the GitHub `pypi` environment, publishes the preserved
artifacts to PyPI through Trusted Publishing, and then creates the GitHub
Release from the matching curated changelog section.

> [!IMPORTANT]
>
> Configure the PyPI Trusted Publisher before the first automated release:
> owner `HisQu`, repository `apprc`, workflow `release.yml`, and environment
> `pypi`. The GitHub environment must require `markur4` as a reviewer. It does
> not contain a PyPI token or any repository secret.

Prepare a release on `main` only after the intended changes have passed CI:

1. Move the final net changes from `[Unreleased]` into a new
   `# MAJOR.MINOR.PATCH - YYYY-MM-DD` section in `CHANGELOG.md`.
2. Update the changelog table of contents, remove empty subsections from the
   released version, and restore every empty subsection under `[Unreleased]`.
3. Commit the finalized changelog and run the repository verification commands.
4. Run `just bump patch`, `just bump minor`, or `just bump major`. The recipe
   refuses to change version files unless the prepared changelog is valid and
   `[Unreleased]` is empty.
5. Inspect the version commit and local tag, then push only those intended refs:

   ```bash
   git push origin main vMAJOR.MINOR.PATCH
   ```

The pushed release tag `v*` triggers the automated github release workflow:

1. Reuse `.github/workflows/ci.yml` for Linux and Windows on every supported
   Python version.
2. Confirm the tag, `pyproject.toml` version, changelog heading, changelog TOC,
   and empty `[Unreleased]` template agree.
3. Run `just publish-check`, reject an uncommitted generated
   `README.pypi.md`, and preserve the wheel, sdist, and release notes as one
   workflow artifact.
4. Wait for approval on the `pypi` environment.
5. Publish the preserved distributions with `uv publish` through GitHub OIDC.
6. Create the GitHub Release only after PyPI accepts the distributions, using
   the same wheel and sdist plus the curated changelog notes.

If CI, metadata validation, or packaging fails, fix the release commit and use
a new version; do not move a tag that has reached the remote. If approval is
rejected, no package or GitHub Release is published. If PyPI succeeds but the
final GitHub command fails, rerun the failed workflow: `uv publish` recognizes
the identical existing PyPI files and the Release step can continue.

After publication, verify the clean package install explicitly:

```bash
just verify-pypi "apprc==MAJOR.MINOR.PATCH"
gh release view vMAJOR.MINOR.PATCH --repo HisQu/apprc
```

> [!NOTE]
>
> PyPI projects do not populate GitHub's Packages panel. AppRC uses the GitHub
> About website, README badges, project URLs, and Releases to link the two
> publication surfaces.

<br>

# 3. Documentation Workflow

<!-- ======================================================== -->

<br>

## Documentation Rules
<!-- ======================================================== -->

Documentation has two audiences:

- Root [README.md](../README.md): short adopter-facing entry point.
- [docs](.): detailed manual, references, explanations, and maintainer notes.

When editing docs:

1. Keep [docs/README.md](README.md) as the reading map.
2. Put procedures in [How-To User Guides](How-To-User-Guides.md).
3. Put exact names in [References](References.md).
4. Put system concepts in [Explanations](Explanations.md).
5. Put repo maintainer workflow in this file.
6. Use exact public names, commands, env vars, filenames, and paths.
7. Link to exact chapters when a section is the real target.
8. Use GitHub callouts consistently.
9. Update docs when setup, CLI behavior, public APIs, env vars, or
   user-visible workflows change.

Avoid vague guidance such as "check settings." Name the setting:
`MYAPP_STORAGE`, `.env.apprc-storage`, `index_filename`,
`config doctor --json`, or the exact path involved.

<br>

<!-- ======================================================== -->

<br>

## README And PyPI README
<!-- ======================================================== -->

`README.pypi.md` is generated from `README.md`. Do not hand-edit the PyPI
README. After changing the root README, run:

```bash
python src/apprc_dev/packaging/pypi_readme.py
```

The generator converts GitHub callouts such as `[!IMPORTANT]` into conservative
Markdown that PyPI can render. The test suite checks that
`README.pypi.md` exactly matches the generated output.

<br>

<!-- ======================================================== -->

<br>

## Documentation Assets
<!-- ======================================================== -->

Docs assets live in [docs/assets](assets). Keep them small and direct.

Rules:

1. Use prose and tables first.
2. Add an image only when it makes a complex relationship easier to see.
3. Keep SVG text readable on GitHub light and dark themes.
4. Replace placeholders before committing.
5. Update the Markdown caption when the figure changes meaning.

Generated figures use the `graphigs` dev dependency and the Graphviz
executables `dot` and `neato`:

```bash
dot -V
neato -V
.venv/bin/python docs/assets/render_all.py
```

Preview renders can target a temporary directory:

```bash
.venv/bin/python docs/assets/render_all.py --output-dir /tmp/apprc-docs-figures
```

The figure scripts keep tracked assets SVG-only. Temporary PNG files produced
by Graphigs are removed by the AppRC export helper.

The README graphical abstract intentionally uses a wide
`FigureBounds`/`SvgDisplayBounds` export override so it can work as a
landscape hero figure. Keep wide export settings local to figures that need
that presentation.

Figure color roles:

| Color | Meaning |
|---|---|
| Blue | Developer-declared contracts and schema inputs. |
| Green | Runtime resolution, dotenv layers, and effective config. |
| Orange | Explicit setup, write commands, and generated CLI workflows. |
| Purple | Inspection surfaces, diagnostics, editor, and provenance. |
| Neutral | AppRC metadata, boundaries, and captions. |

Current assets:

| Asset | Generator | Owner Markdown |
|---|---|---|
| `docs-reading-map.svg` | [docs_reading_map.py](assets/docs_reading_map.py) | [docs/README.md](README.md) |
| `apprc-runtime-layers.svg` | [apprc_runtime_layers.py](assets/apprc_runtime_layers.py) | [Explanations.md](Explanations.md) |
| `apprc-abstract-user-journey.svg` | [apprc_abstract_user_journey.py](assets/apprc_abstract_user_journey.py) | [README.md](../README.md) |
| `apprc-abstract-contract-workflows.svg` | [apprc_abstract_contract_workflows.py](assets/apprc_abstract_contract_workflows.py) | [README.md](../README.md#how-apprc-works) |
| `apprc-abstract-layer-cake.svg` | [apprc_abstract_layer_cake.py](assets/apprc_abstract_layer_cake.py) | [Explanations.md](Explanations.md#runtime-bootstrap) |
| `apprc-storage-config-locations.svg` | [apprc_storage_config_locations.py](assets/apprc_storage_config_locations.py) | [Explanations.md](Explanations.md#storage-selection) - dotenv locations and kit-shape use |

<br>

# 4. Verification

<!-- ======================================================== -->

<br>

## Docs Verification
<!-- ======================================================== -->

For docs-only changes:

```bash
dot -V
neato -V
.venv/bin/python docs/assets/render_all.py
python src/apprc_dev/packaging/pypi_readme.py
.venv/bin/pytest tests/test_pypi_readme.py
git diff --check
rg -n "\\{[m]y_project\\}|README\\.[I]GNORE|\\.env\\.[l]ocal|config [i]nit|config [l]ist|content[R]eference|oai[_]cite" README.md README.pypi.md docs
```

The `rg` command should return no matches.

<br>

<!-- ======================================================== -->

<br>

## Python Verification
<!-- ======================================================== -->

For code changes:

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
python -m apprc_dev.example_apps.bootstrap --clean
```

Run focused tests first for narrow changes. Run the broader suite when shared
behavior, public facades, CLI generation, or bootstrap behavior changes.

<br>

<!-- ======================================================== -->

<br>

## Review Checklist
<!-- ======================================================== -->

Before finishing:

- Check `git status --short`.
- Review `git diff`.
- Confirm unrelated user changes were not reverted.
- Confirm public docs match current public APIs.
- Confirm generated `README.pypi.md` is updated when `README.md` changed.
- Confirm links point to real files and relevant chapters.
- Confirm new docs avoid stale filenames and removed commands.
- Include a copyable commit message in the final report.

> [!NOTE]
> Related: use [References: project paths](References.md#project-paths) for
> exact source owners.
