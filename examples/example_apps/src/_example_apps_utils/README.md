# Example App Utilities

`_example_apps_utils` is internal support code for the repository-local
examples. It is not a user app template.

## What It Provides

- The example app registry used by the bootstrap helper.
- Shared CLI helper functions used by the runnable apps.
- The `apprc-examples-run-all` scenario runner.

## Requirements

The package is installed as part of the dev-only
`examples/example_apps` editable package.

## Commands

```bash
apprc-examples-run-all
```

## Upgrade Options

Do not copy this package into downstream applications. Copy one runnable app
package instead, then replace its app name, env prefixes, fields, and command
name.

## Docs

- [Example app overview](../../README.md)
- [Development guide](../../../../docs/Development.md#example-apps)
