# Development

[Documentation](README.md) · [Explanations](Explanations.md) · [How-to user guides](How-To-User-Guides.md) · [References](References.md) · [Examples](EXAMPLES.md)

- [Work in the repository](#work-in-the-repository)
  - [Environment](#environment)
  - [Source ownership](#source-ownership)
- [Verify and update changes](#verify-and-update-changes)
  - [Checks](#checks)
  - [Documentation checks](#documentation-checks)
  - [Actions artifact diagnostic](#actions-artifact-diagnostic)
  - [README maintenance](#readme-maintenance)
  - [Generated files](#generated-files)
- [Build and release AppRC](#build-and-release-apprc)
  - [Build the three distributions](#build-the-three-distributions)
  - [Release procedure](#release-procedure)

<br>

# Work in the repository

## Environment

CI runs only on Ubuntu: core checks cover Python 3.12, 3.13, and 3.14, and
GUI/browser checks cover Python 3.12. Windows and macOS runtime and installer
code remain, but those platforms are unverified by this CI policy. Existing
[native installation and UI test failures](../BACKLOG.md#p2--e1-tooling---windows-and-macos-installation-ci-fails)
remain unresolved; a green Linux run does not establish native compatibility.
`uv`, `direnv`, and `just` are conveniences. Runtime, builds, and pip development
installs do not require their commands.

Ordinary pip setup from the repository root:

```shell
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e . -e src/apprc_dev/packaging/terminal -e src/apprc_dev/packaging/gui -e examples/example_apps --group dev
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

The root uv workspace includes the terminal and GUI projects. Root source
mappings select all three local distributions and the editable examples. Do not change
shell startup files or `PATH` to locate project tools; use `.venv/bin/<tool>`.

## Source ownership

| Path | Purpose |
| --- | --- |
| `src/apprc/definition` | Validated metadata, path declarations, and shared records |
| `src/apprc/runtime` | Explicit resolution, path snapshots, and config lifecycle |
| `src/apprc/services` | Config, workspace, maintenance and installation orchestration |
| `src/apprc/user_files` | File parsing, ownership, persistence, workspace operations |
| `src/apprc/interfaces` | Typer and Textual adapters |
| `src/apprc/public` | Application declaration facade |
| `src/apprc/scaffold` | Small generated application layout |
| `src/apprc/distribution` | Author APIs, external templates and the explicit standalone module/resource closure |
| `src/apprc/distribution/runtime` | Ordinary composable acquisition, probing, saved management and removal code; no Jinja dependency |
| `src/apprc/user_files/installation` | Strict installation authority I/O, revision checks, locks and migration |
| `src/apprc/interfaces/tui/launcher` | Optional single-event-loop management and foreground-command interface |
| `src/apprc_dev/packaging` | Metadata generation, install checks, release helpers |
| `src/apprc_dev/packaging/gui/src/apprc_gui` | Gradio presentation; no copy of the core's `apprc` modules |
| `tests` | Behavior, architecture, and integration checks |
| `examples/example_apps` | Curated CLIs, automated runner, manual lab |
| `docs/assets` | Diagram source scripts and generated SVGs; generated diagrams must follow their source scripts |

The root project builds `apprc-core` and owns all `apprc` Python files. The
`src/apprc_dev/packaging/terminal` project builds `apprc`, owns no Python package,
and supplies dependencies plus the console entrypoint. Never add a second copy
of an `apprc` module to that wrapper.
`src/apprc_dev/packaging/gui` builds `apprc-gui`, which owns only `apprc_gui`.
Its `ConfigEditor` calls `ConfigManager`; it does not implement file writes.

Production `__init__.py` files contain imports and module docstrings only.
Architecture tests enforce declaration dependency direction. The installation
schema belongs in `definition/installation.py`; filesystem authority and
coordination belong in `user_files/installation`; application-bound orchestration
belongs in `services/installation.py`. Do not put business configuration or
generator dependencies into those lower layers.

Current installation recovery resumes only operations represented by schema-2
authority. Resource/layout migration still moves explicitly enumerated,
revision-checked files and preserves unknown content; it is not receipt adoption.
Validate the inventory before publishing pending authority and again when
resuming it: decoded path types alone do not establish containment. Schema-1
installation records require the explicit
[reinstallation procedure](How-To-User-Guides.md#from-installation-record-schema-1),
not a version-number edit or automatic conversion.

`ConfigEditorScreen` owns workspace presentation state and the single
post-action refresh boundary. Workflows receive a fresh, read-only
`WorkspaceActionContext` and return `WorkspaceActionResult`; they do not retain
the screen or mutate its registry, selection, or controls. Persistent operations
remain in `ConfigManager` and `WorkspaceManager`. A failed registry reload makes
registry actions unavailable without locking valid user-config editing.

Application packaging/release manifests and business actions remain in the
consuming repository. Its `_distr` generator and payload are author inputs,
not installed application imports. Maintain substantial lifecycle logic as
ordinary Python and serialize complete explicitly included files into standalone
support. Never extract function source, rewrite Python, or create a second
installer implementation as a large template.

`distribution/runtime/saved_management.py` is the canonical stdlib-only saved
program. Rendering copies that source and serializes portable `management.json`
data; `runtime/installation.py::bind_install_support()` binds the validated
external interpreter in JSON, not by inspecting or rewriting Python. Native
frontend path escaping is a separate binding concern. Keep both program and
binding data in the record's exact support-digest inventory.

<br>

# Verify and update changes

## Checks

```shell
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest
.venv/bin/pytest src/apprc_dev/packaging/gui/tests
.venv/bin/playwright install chromium
.venv/bin/apprc-examples-run-all
.venv/bin/python src/apprc_dev/packaging/terminal_metadata.py --check
git diff --check
```

Run focused tests during implementation, then the full suite for shared changes.
The example runner creates disposable application directories, exercises setup,
resolution and doctor, and checks cleanup. `apprc-examples-lab` opens an isolated
manual session. See [examples](../examples/example_apps/README.md).
The GUI tests include a browser-level check and require the Chromium binary
installed by `playwright install chromium`.

`just lock` regenerates `uv.lock` and `pylock.toml`; `just sync` installs locked
dependencies. `just clean` removes caches and build outputs.

Development checks verify supported APIs, not the complete absence of obsolete
import paths. Empty directories left by historical checkouts can be importable
as namespace packages without providing any legacy implementation. Do not
globally delete caches to satisfy an import-absence assertion. Artifact-consumer
checks still verify distribution ownership, supported imports, console commands,
and preservation of the core when the terminal wrapper is removed.

## Documentation checks

Follow the [documentation rules](README.md#documentation-rules), including the
fixed [component names](README.md#component-names). Explanations defines components;
How-to user guides implements tasks; Examples assembles complete setups;
References states the exact contracts. Link the relevant words between them.

```shell
.venv/bin/pytest tests/test_documentation.py
.venv/bin/python examples/section_bundle.py
.venv/bin/python examples/dependency_config_import.py
```

The tests check document links, heading hierarchy, table-of-contents order,
major-section spacing, and anchors. They also execute the marked independent
Python examples in temporary directories. Review prose separately: tests cannot
determine whether an explanation teaches a component clearly. Verify expected
values, file effects, and prerequisites whenever changing an example.

Keep complete application sources in `examples`; link to those sources from
Examples. The HTML `example-file` comments in guides associate code blocks with
files for execution tests and are hidden in rendered Markdown.

## Actions artifact diagnostic

The separate [Diagnostics workflow](../.github/workflows/diagnostics.yml)
uploads a tiny text artifact, downloads that exact artifact by ID, and compares
the payload byte-for-byte. It needs no checkout, Python installation, configured
secrets, or repository-write permission. It runs independently of normal CI and
application tests.
A successful run proves that Actions artifact round-trip for that run only,
not application correctness, GitHub Release uploads, PyPI publication, every
quota type, or future quota availability.

Once the workflow exists on default `main`, invoke it manually from the
repository root with the GitHub CLI. Replace `<branch>` with the ref to run:

```shell
gh workflow run diagnostics.yml --ref <branch>
```

Before it exists on default `main`, the initial feature-branch invocation is a
push to `diagnostics/artifact-upload` that changes
`.github/workflows/diagnostics.yml`. Both the branch and changed path must match;
ordinary later use is manual.

The artifact is named `diagnostic-RUN_ID-RUN_ATTEMPT` and has one-day fallback
retention; the workflow does not delete it immediately. After inspecting the
accepted run, find its artifact ID and delete only that artifact. Replace
`OWNER`, `REPO`, and `RUN_ID` with the repository and accepted run, then use the
returned `id` for `ARTIFACT_ID`:

```shell
gh api repos/OWNER/REPO/actions/runs/RUN_ID/artifacts --jq '.artifacts[] | {id, name}'
gh api --method DELETE repos/OWNER/REPO/actions/artifacts/ARTIFACT_ID
```

This cleanup concerns Actions artifact storage, not GitHub Release assets or
PyPI files.

## README maintenance

The root README follows BuildBen's
[`_README.md` design](https://github.com/HisQu/buildben/blob/main/src/buildben/_templates_proj/_README.md).
Read the complete README before editing it. Adapt it in place: preserve the
centered header, badges, graphical abstract, heading hierarchy, spacing,
numbered table of contents, and audience-grouped documentation navigation.
Never replace it with a generic README or drop useful content just to shorten
a rewrite. Update facts and navigation within the chosen design.

When an API or usage change invalidates the overview, update its producer,
generated SVG, caption, and affected prose/examples together. Do not leave a
stale picture or remove the picture instead of maintaining it. Diagram scripts
are canonical; generated SVGs and package READMEs must not be hand-edited.

Regenerate the overview alone, then both package descriptions:

```shell
.venv/bin/python docs/assets/apprc_abstract_configuration_overview.py
.venv/bin/python src/apprc_dev/packaging/pypi_readme.py
.venv/bin/python src/apprc_dev/packaging/terminal_metadata.py
```

Run the [documentation checks](#documentation-checks), the existing
`tests/test_pypi_readme.py` tests, and
`.venv/bin/python src/apprc_dev/packaging/terminal_metadata.py --check`.
Keep incoming links synchronized when headings change. Link and generated-content
checks do not establish visual fidelity or diagram meaning: inspect the rendered
README and SVG against the template and current
[component definitions](README.md#component-names).

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

<br>

# Build and release AppRC

## Build the three distributions

Ordinary PEP 517 builds:

```shell
.venv/bin/python -m build --outdir dist
.venv/bin/python -m build src/apprc_dev/packaging/terminal --outdir dist
.venv/bin/python -m build src/apprc_dev/packaging/gui --outdir dist
.venv/bin/python -m twine check dist/*
.venv/bin/python src/apprc_dev/packaging/artifact_check.py dist
```

Start with an empty `dist` directory. Expect three wheels and three source archives
with matching versions. `python -m build` builds a wheel from each sdist, checking
that it is self-contained. `artifact_check.py` uses fresh ordinary pip virtual
environments for core, terminal, and GUI installs and wrapper removal. It checks
wheel file ownership for overlap and confirms the core can construct and manage
config without terminal imports or an `apprc` console entrypoint.

To check migration from a previously built single-distribution wheel:

```shell
.venv/bin/python src/apprc_dev/packaging/artifact_check.py dist --previous-wheel previous/apprc-OLD-py3-none-any.whl
```

This exercises the documented uninstall-old-then-install-new procedure. It does
not promise safe transfer of overlapping ownership during a plain pip upgrade.

The equivalent uv build commands use `uv build --no-sources --package` with
`apprc-core`, `apprc`, and `apprc-gui` in that order.

## Release procedure

Update the changelog first. Any change requiring consumer code, configuration,
or installation changes belongs under breaking changes with affected users and
migration instructions. Keep the core, terminal, and GUI distribution versions
in sync. Release preparation syncs the GUI version and its exact `apprc-core`
pin automatically.

`just publish-check` rehearses Linux Python 3.12–3.14 checks, generated metadata,
all three distributions, pip installation checks, and publication dry runs. It
uploads nothing. `just release-prepare <patch|minor|major>` changes the root
version, regenerates terminal metadata, syncs the GUI version and core pin,
refreshes the locks, checks the release, and prepares a local commit and tag.
`just release-push TAG` is the separate remote action.

Tag CI reuses the same Ubuntu-only core and GUI/browser checks described in
[Environment](#environment); it does not verify Windows or macOS. The release workflow
attaches all six artifacts to GitHub, then publishes `apprc-core` before `apprc`
and `apprc-gui`.
Each project uses its own PyPI check URL so retries can skip already uploaded
artifacts. `just publish-pypi TAG` requests publication of an existing validated
release, rather than rebuilding it.

> [!IMPORTANT]
> Trusted publishing must be configured for all three PyPI projects before release.
> Preparing this repository does not create the `apprc-core` project or change
> external PyPI settings. Do not publish a wrapper until its matching core is
> available.

The [Gradio editor](Explanations.md#gradio-editor) has a separate source package.
A consuming application owns its installer and tests it on Windows. AppRC
itself does not publish an installer.
