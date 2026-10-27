# CLI Runtime Example

`cli_runtime` demonstrates the advanced path: an app-owned Typer callback
passes AppRC options into `rc.cli.CliRuntime`, then adds its own runtime state.
Its `APPRC_EXAMPLE_RUNTIME_WORKSPACE` selector accepts a registered name or path.

Start a clean session:

```bash
apprc-examples-lab cli-runtime
```

After the printed workspace setup and required-token commands, compare:

```bash
apprc-cli-runtime status
apprc-cli-runtime --workspace default --workdir PATH --model demo --dry-run run
```

`status` is declared runtime-independent and works before workspace setup. `run`
requires AppRC resolution and receives `workdir`, `model`, and `dry_run` in
the app-owned `RuntimeState`.

Copy [`cli.py`](cli.py) only when the simpler `rc.cli.mount_app_cli(app, MyRC)`
pattern is not enough. The other seven examples use that shorter integration.

See the [example inventory](../../README.md#example-inventory) and
[public CLI interfaces](../../../../docs/References.md#public-namespaces).
