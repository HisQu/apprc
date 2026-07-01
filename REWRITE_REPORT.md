# AppRC Rewrite Report

This pass completed the package-architecture rewrite and kept runtime behavior
stable. The items below are intentional follow-up candidates I did not change
because they would broaden the behavior or API surface beyond this refactor.

## Deferred Design Decisions

### Lazy aggregate facades

`apprc.runtime`, `apprc.user_files`, `apprc.user_files.storage_roots`, and
`apprc.logging` still use the shared lazy facade helper. Eager imports created
cycles around `EnvConfig`, `AppConfigSpec`, storage loading, and logging setup.
The root `apprc` facade imports the main application APIs eagerly so Pyright and
normal app code see precise types, while the deeper aggregate packages stay
lazy.

Future pass: reduce import cycles enough that these package facades can become
plain import-only `__init__.py` files.

### Root facade size

The root `apprc.__init__` is intentionally large because the new integration
rule is `import apprc` followed by `apprc.<name>`. It now exports config
definition, runtime bootstrap, diagnostics, CLI/TUI hooks, dotenv helpers,
storage helpers, provenance helpers, utility helpers, and optional logging.

Future pass: add a generated public-surface snapshot test so this facade stays
explicit without becoming surprising.

### TUI internals

The TUI files moved into `apprc.interfaces.tui`, but the editor, modal, and
workflow internals remain behavior-preserving moves. Some modules are still
large because splitting them further would need more UI-state regression work.

Future pass: split editor workflows by user action and add more TUI interaction
tests before changing that shape.

### CLI command internals

The generated config command handler was split into runtime, storage, app-wide,
editor, and selector-context modules. The shared `_base.py` is still broad
because it owns cross-command Typer context recovery, selector resolution, and
runtime payload handling.

Future pass: extract only after adding more focused tests around selector
context fallback and bootstrapless command state.

### Diagnostics payload shape

Diagnostics now separate `payload.py`, `messages.py`, and `_diagnosis.py`, but
`ConfigDoctorPayload` remains a large `TypedDict` because CLI JSON output,
tests, and downstream tooling expect the current shape.

Future pass: consider a dataclass model with an explicit `.to_payload()` method
after deciding whether JSON keys are locked as public API.

### Haiu logging adapter imports

Haiu production code that used removed AppRC packages was moved to the root
facade. A few Haiu logging adapter modules still import `apprc.logging`
directly because they adapt that logging-specific package and AppRC still keeps
`apprc.logging` as a public subpackage.

Future pass: decide whether `apprc.logging` should remain a documented
specialized import path or whether Haiu should use only root logging names too.

### Test file names

Some AppRC test filenames still contain `runtime_config` because they now assert
the removal of the old package. I left those names in place to avoid noisy test
renames during the architecture move.

Future pass: rename those tests to architecture-oriented names once this
breaking rewrite settles.
