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
| Example lab and smoke runner | [examples/example_apps/src/_example_apps_utils](../examples/example_apps/src/_example_apps_utils) |
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
script per integration scenario and two test utilities:

| Script | AppRC Surface |
|---|---|
| `apprc-config-only` | Direct `rc.AppRC(...)` without storage |
| `apprc-config-with-storage` | Direct `rc.AppRC(...)` with `rc.Storage(...)` |
| `apprc-explicit-env-precedence` | Explicit env-file selector precedence |
| `apprc-cli-runtime` | `CliRuntime` with an app-owned callback |
| `apprc-examples-lab EXAMPLE` | One disposable interactive shell |
| `apprc-examples-run-all` | Real-CLI non-interactive smoke runner |

The source tree intentionally uses one Python package per app so the examples
match what a downstream project should copy:

| Package | Purpose |
|---|---|
| `config_only` | Config-only app with packaged and per-user values. |
| `config_with_storage` | Storage app with app and storage-local values. |
| `explicit_env_precedence` | Storage selector precedence with explicit env files. |
| `cli_runtime` | Typer callback integration through `CliRuntime`. |
| `_example_apps_utils` | Lab, registry, and smoke runner; not a user app template. |

The four application packages must not import `_example_apps_utils`. Each one
is a copyable downstream pattern; test orchestration belongs in the utility
package.

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
  apprc.defaults.env
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
  --storage \
  --app-id myapp \
  --display-name "My App" \
  --storage-selector-env-key MYAPP_STORAGE \
  --target src
```

Install the example console scripts when the dev dependency group has not
already installed them:

```bash
python -m pip install -e ".[tui]" -e examples/example_apps --no-build-isolation
```

Open one clean manual-test shell:

```bash
apprc-examples-lab config-only
apprc-examples-lab config-with-storage
apprc-examples-lab explicit-env-precedence
apprc-examples-lab cli-runtime
```

The lab strips inherited `APPRC_EXAMPLE_*` variables, points the selected
application's `<APP>_APPRC_DIR` at a temporary root, and opens the current
user's shell before any AppRC files exist. It prints a scenario-specific
walkthrough and removes its root when the shell exits. It never owns or removes
paths the tester explicitly selects outside that root.

Direct example CLI calls remain realistic and can leave persistent AppRC files.
Use the aggregate command for an isolated automated pass:

```bash
apprc-examples-run-all
```

The runner calls the installed application CLIs as subprocesses and covers
setup, doctor, runtime, and purge. Its precedence case proves both policies
with different roots and values. Pytest covers the common command surface on
all four apps, the complete storage lifecycle on `config_with_storage`, name
and path selectors, runtime skipping, headless editor launch, and lab cleanup.
It does not claim every generated command runs against every example.

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
3. If `README.md` changed, regenerate the tracked PyPI variant and include it
   in the release-preparation commit:

   ```bash
   python src/apprc_dev/packaging/pypi_readme.py
   ```

4. Commit the finalized changelog and generated README, then run
   `just release patch`, `just release minor`, or `just release major`. The
   recipe:
   - refuses to start from a dirty worktree;
   - validates the prepared changelog before changing version files;
   - temporarily bumps `pyproject.toml`, `uv.lock`, and `pylock.toml`;
   - runs the complete `just publish-check` rehearsal;
   - creates the version commit and annotated tag only after every check passes.
5. Inspect the version commit and local tag, then push only those intended refs:

   ```bash
   git push origin main vMAJOR.MINOR.PATCH
   ```

`publish-check` uses temporary locked environments and leaves the active
project `.venv` unchanged. It runs the complete Linux CI command sequence under
Python 3.12, 3.13, and 3.14, validates the release metadata and generated
README, builds a clean wheel and sdist, runs Twine, smoke-tests the wheel under
all three Python versions and the sdist under Python 3.12, and finishes with a
non-interactive `uv publish --dry-run`. The dry run uses a fixed non-secret
placeholder token because `uv publish` requires an upload credential even when
no files will be uploaded. `uv` may describe simulated uploads, but the recipe
ends with explicit confirmation that nothing was published and prints the next
manual release command.

If the rehearsal or version commit fails, `release` restores all three version
files and creates no commit or tag. Fix the reported problem, commit any source
correction such as a regenerated `README.pypi.md`, and rerun `release`. If the
version commit succeeds but annotated-tag creation alone fails, the recipe
prints the exact `git tag -a ...` retry command and retains the clean version
commit.

> [!NOTE]
>
> The local rehearsal cannot reproduce Windows, GitHub environment approval,
> OIDC token issuance, the real PyPI upload, or GitHub Release creation. The
> pushed tag remains subject to those GitHub-hosted gates.

The pushed release tag `v*` triggers the automated GitHub release workflow:

1. Reuse `.github/workflows/ci.yml` for Linux and Windows on every supported
   Python version.
2. Reuse the artifact stage from `publish-check` to confirm the tag, project
   version, changelog heading, changelog TOC, empty `[Unreleased]` template,
   generated README, wheel, sdist, install smoke checks, and publication dry
   run without repeating the Linux source-check matrix.
3. Preserve the wheel, sdist, and release notes as one workflow artifact.
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
`MYAPP_STORAGE`, `apprc.storage.env`, `apprc_toml_filename`,
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
apprc-examples-run-all
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
