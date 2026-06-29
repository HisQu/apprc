<!-- ======================================================== -->

<br>

## Table Of Contents
<!-- ======================================================== -->

1. [Development](#1-development)
2. [Maintainer Workflow](#2-maintainer-workflow)
   1. [Before Editing](#before-editing)
   2. [Repository Routing](#repository-routing)
   3. [Environment Setup](#environment-setup)
3. [Documentation Workflow](#3-documentation-workflow)
   1. [Documentation Rules](#documentation-rules)
   2. [README And PyPI README](#readme-and-pypi-readme)
   3. [Documentation Assets](#documentation-assets)
4. [Verification](#4-verification)
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
| Runtime config contracts, bootstrap, storage, dotenv, doctor, setup, TUI | [src/apprc/runtime_config](../src/apprc/runtime_config) |
| Typer command integration and CLI presentation | [src/apprc/cli](../src/apprc/cli) |
| Optional semantic logging | [src/apprc/logging](../src/apprc/logging) |
| Broad AppRC utility helpers | [src/apprc/utils](../src/apprc/utils) |
| Public facade exports | [src/apprc/__init__.py](../src/apprc/__init__.py) and package `__init__.py` files |
| Example host app | [examples/apprc_example_app](../examples/apprc_example_app) |
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
