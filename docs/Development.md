# Development

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Examples](EXAMPLES.md)

- [Environment](#environment)
- [Source ownership](#source-ownership)
- [Checks](#checks)
- [Documentation checks](#documentation-checks)
- [Generated files](#generated-files)
- [Build both distributions](#build-both-distributions)
- [Release procedure](#release-procedure)

## Environment

The repository supports Python 3.12 through 3.14 in CI on Linux and Windows.
`uv`, `direnv`, and `just` are conveniences. Runtime, builds, and pip development
installs do not require their commands.

Ordinary pip setup from the repository root:

```shell
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e . -e src/apprc_dev/packaging/terminal -e examples/example_apps --group dev
```

On Windows use `.venv\Scripts\python.exe`. The `dev` dependency group includes
tests, Ruff, Pyright, build/metadata tools, diagrams, and examples. If developing
only the core, `python -m pip install -e .` is sufficient for its dependencies.
Install local examples with `python -m pip install -e examples/example_apps`
after installing the local terminal wrapper.

For the locked development environment:

```shell
uv sync --locked --all-groups
```

The root uv workspace includes the metadata-only terminal project. Root source
mappings select both local distributions and the editable examples. Do not change
shell startup files or `PATH` to locate project tools; use `.venv/bin/<tool>`.

## Source ownership

| Path | Purpose |
| --- | --- |
| `src/apprc/definition` | Validated metadata and shared records |
| `src/apprc/runtime` | Explicit resolution and config lifecycle |
| `src/apprc/services` | Shared manager and field inspection |
| `src/apprc/user_files` | File parsing, persistence, storage operations |
| `src/apprc/interfaces` | Typer and Textual adapters |
| `src/apprc/public` | Application declaration facade |
| `src/apprc/scaffold` | Small generated application layout |
| `src/apprc_dev/packaging` | Metadata generation, install checks, release helpers |
| `tests` | Behavior, architecture, and integration checks |
| `examples/example_apps` | Curated CLIs, automated runner, manual lab |
| `docs/assets` | Diagram sources and generated SVGs |

The root project builds `apprc-core` and owns all `apprc` Python files. The
`src/apprc_dev/packaging/terminal` project builds `apprc`, owns no Python package,
and supplies dependencies plus the console entrypoint. Never add a second copy
of an `apprc` module to that wrapper.

Production `__init__.py` files contain imports and module docstrings only.
Architecture tests enforce declaration dependency direction. Put future GUI
presentation in interfaces and future build tooling outside runtime.

## Checks

```shell
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
.venv/bin/apprc-examples-run-all
.venv/bin/python src/apprc_dev/packaging/terminal_metadata.py --check
git diff --check
```

Run focused tests during implementation, then the full suite for shared changes.
The example runner creates disposable application directories, exercises setup,
resolution and doctor, and checks cleanup. `apprc-examples-lab` opens an isolated
manual session. See [examples](../examples/example_apps/README.md).

`just lock` regenerates `uv.lock` and `pylock.toml`; `just sync` installs locked
dependencies. `just clean` removes caches and build outputs. Obsolete empty
namespace directories can survive historical in-place checkouts; the remaining
cleanup question is tracked in [TODO.md](../TODO.md#todo-list).

## Documentation checks

Follow the [documentation rules](README.md#documentation-rules), including the
fixed [component names](README.md#component-names). Explanations defines components;
How-to user guides implements tasks; Examples assembles complete setups;
References states the exact contracts. Link the relevant words between them.

```shell
.venv/bin/pytest tests/test_documentation.py
.venv/bin/python examples/section_bundle.py
```

The tests check document links and anchors and execute the marked independent
Python examples in temporary directories. Review prose separately: tests cannot
determine whether an explanation teaches a component clearly. Verify expected
values, file effects, and prerequisites whenever changing an example.

Keep complete application sources in `examples`; link to those sources from
Examples. The HTML `example-file` comments in guides associate code blocks with
files for execution tests and are hidden in rendered Markdown.

## Generated files

Edit source documentation and diagram scripts, then regenerate:

```shell
.venv/bin/python docs/assets/render_all.py
.venv/bin/python src/apprc_dev/packaging/pypi_readme.py
.venv/bin/python src/apprc_dev/packaging/terminal_metadata.py
```

The PyPI README generator rewrites repository links and GitHub callouts.
The terminal generator copies shared metadata, description, and license from
the root and pins `apprc-core` to its exact version. Its `--check` mode rejects
stale generated files. Commit generated files with their source changes.

## Build both distributions

Ordinary PEP 517 builds:

```shell
.venv/bin/python -m build --outdir dist
.venv/bin/python -m build src/apprc_dev/packaging/terminal --outdir dist
.venv/bin/python -m twine check dist/*
.venv/bin/python src/apprc_dev/packaging/artifact_check.py dist
```

Start with an empty `dist` directory. Expect two wheels and two source archives
with matching versions. `python -m build` builds a wheel from each sdist, checking
that it is self-contained. `artifact_check.py` uses fresh ordinary pip virtual
environments for core and terminal installs and wrapper removal. It checks wheel
file ownership for overlap and confirms the core can construct and manage config
without terminal imports or an `apprc` console entrypoint.

To check migration from a previously built single-distribution wheel:

```shell
.venv/bin/python src/apprc_dev/packaging/artifact_check.py dist --previous-wheel previous/apprc-OLD-py3-none-any.whl
```

This exercises the documented uninstall-old-then-install-new procedure. It does
not promise safe transfer of overlapping ownership during a plain pip upgrade.

The equivalent uv build commands are `uv build --package apprc-core --no-sources`
and `uv build --package apprc --no-sources`.

## Release procedure

Update the changelog first. Any change requiring consumer code, configuration,
or installation changes belongs under breaking changes with affected users and
migration instructions. Version 0.25.0 is prepared locally with matching core
and terminal metadata. It has not been tagged or published.

`just publish-check` rehearses Linux Python 3.12–3.14 checks, generated metadata,
both distributions, pip installation checks, and publication dry runs. It uploads
nothing. `just release-prepare <patch|minor|major>` changes the root version,
regenerates the wrapper and locks, checks the release, and prepares a local commit
and tag. `just release-push TAG` is the separate remote action.

Tag CI keeps Linux/Windows and Python 3.12–3.14 coverage. The release workflow
attaches all four artifacts to GitHub, then publishes `apprc-core` before `apprc`.
Each project uses its own PyPI check URL so retries can skip already uploaded
artifacts. `just publish-pypi TAG` requests publication of an existing validated
release, rather than rebuilding it.

> [!IMPORTANT]
> Trusted publishing must be configured for both PyPI projects before release.
> Preparing this repository does not create the `apprc-core` project or change
> external PyPI settings. Do not publish a wrapper until its matching core is
> available.

Toga, cx_Freeze, and platform installer verification are future work. Cross-process
write coordination must precede shipping concurrent GUI editing.
