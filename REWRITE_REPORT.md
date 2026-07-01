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

### Host CLI runtime semantics

`ConfigCliBridge` now carries the host-owned callback integration, runtime
bootstrap policy, config group mounting, and app-owned state construction. The
behavior is useful, but the names still describe the mechanism instead of the
domain. The intended concept is a host CLI runtime coordinator: AppRC decides
when runtime bootstrap is needed, preserves enough context for runtime-free
commands, and builds app-owned state for commands that need the runtime.

Future pass: rename the public API before the next release so the semantics are
clear. Candidate names:

- `ConfigCliBridge` -> `HostCliRuntime`
- `ConfigCliSession` -> `HostCliSession`
- `HostCliBootstrapPolicy` -> `HostCliRuntimePolicy`
- `BootstraplessCommand` -> `RuntimeFreeCommand`
- `bootstrap_policy=` -> `runtime_policy=`

Keep compatibility aliases only if this API has already been published in a
release. If not, prefer the clearer names directly and update examples, docs,
tests, and facade exports in the same pass.

### Host CLI option preservation

`ConfigCliBridge.prepare()` accepts a generic host option object, but
`CliBootstrapContext` currently stores only the normalized AppRC subset as
`CliBootstrapOptions`. That means app-specific host options are available to
`state_factory`, but they are lost for skipped-runtime-bootstrap paths unless an
application stores them separately.

Future pass: make the context generic over the original host option type and
preserve both layers explicitly, for example:

- `bootstrap_options: CliBootstrapOptions`
- `host_options: OptionsT`
- `env_bootstrap: EnvBootstrapResult | None`
- `skipped_runtime_bootstrap: bool`

Add a public typed reader such as `host_options_from(ctx, expected_type)` so
applications can recover their full option object from Typer context metadata.
This should let host applications remove custom `ctx.meta` storage when
runtime-free command groups still need forwarded app-specific options.

### Host CLI forwarding helpers

AppRC already exposes `args_provider`, `apprc_options_to_args()`, and
`run_typer_app()`, but nested in-process CLIs still need local glue when the
parent command constructs child argv and the child runtime policy must inspect
those forwarded tokens.

Future pass: add a small forwarding helper around the runtime coordinator,
such as `runtime.forwarded_args(args)` or `runtime.run_forwarded(...)`, so host
applications do not need their own `ContextVar` plus `dataclasses.replace()`
pattern. Keep domain-specific option serialization in the application unless
AppRC grows an explicit registry for extra host options.

### Dev-only example package boundary

The runnable examples now live in one dev-only distribution with separate app
packages for each AppRC mode. The bootstrap helper dynamically imports their
`config.KIT` objects so downstream repositories that type-check only
`../apprc/src` do not also need `../apprc/examples/example_apps/src` on their
static type path.

Future pass: if examples grow beyond smoke coverage, consider adding a tiny
`apprc-example-apps` test helper API that exposes the example kit registry
directly. Keep it outside the production `apprc` package.

### Default CLI state subclassing

`DefaultConfigCliState` is the generic state model used by generated config
commands, but application CLI state often wants to inherit from it and add
required runtime fields. Regular dataclass field ordering can make that awkward
when a base class has default-valued fields.

Future pass: make `DefaultConfigCliState` subclass-friendly, likely with
`@dataclass(slots=True, kw_only=True)`, and update examples and docs to subclass it when
they expose app-owned CLI state to generated config commands.

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

Future pass: From now on, all required logging functionality should be accessed like this:

```
import apprc

apprc.AppLogger(...)
apprc.LoggingConfig(...)
...
```

This replaces this pattern (taken from HAIU):

```
from apprc.logging import (
    AppConsoleRenderer,
    AppLogger,
    LoggingConfig,
    LoggingRenderer,
    async_telemetry,
    forward_cli_output,
    get_logger,
    install_app_logger_class,
    new_cid,
    set_cid,
    with_async_telemetry,
)
from apprc.logging import setup_logging as _setup_app_logging
from apprc.logging.exceptions import REDACTED_VALUE
from apprc.logging.levels import SEMANTIC_EVENTS, SemanticEvent

```


### Test file names

Some AppRC test filenames still contain `runtime_config` because they now assert
the removal of the old package. I left those names in place to avoid noisy test
renames during the architecture move.

Future pass: rename those tests to architecture-oriented names once this
breaking rewrite settles.
