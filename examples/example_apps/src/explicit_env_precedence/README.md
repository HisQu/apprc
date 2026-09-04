# Explicit Env Precedence Example

`explicit_env_precedence` makes selector and value precedence observable. Its
`APPRC_EXAMPLE_PRECEDENCE_STORAGE` selector accepts a registered name or path.

Start a clean session:

```bash
apprc-examples-lab explicit-env-precedence
```

The lab prints commands that create `default` and `explicit` roots, give them
different labels, and write an explicit dotenv file. It then exports shell
values and runs both policies:

```bash
apprc-explicit-env-precedence --env-file EXPLICIT_ENV run
apprc-explicit-env-precedence --env-file EXPLICIT_ENV --env-file-overrides-os-environ run
```

The first command reports the shell-selected root and `shell` label. The
second reports the explicit-file-selected root and `explicit-file` label. This
shows that AppRC preserves its existing conditional precedence; explicit files
do not always override the process environment.

Copy [`cli.py`](cli.py) when an app needs to expose and test explicit dotenv
precedence directly.

See the [example inventory](../../README.md#example-inventory) and
[runtime precedence explanation](../../../../docs/Explanations.md#runtime-bootstrap).
