# Example App Utilities

`_example_apps_utils` is test infrastructure, not an application template.

It owns:

- the four-command registry;
- `apprc-examples-lab`, which opens one disposable shell;
- `apprc-examples-run-all`, which invokes the real installed CLIs.

The user-facing application packages do not import this package. Copy one of
those packages instead.

See the [example overview](../../README.md) and
[development guide](../../../../docs/Development.md#example-apps).
