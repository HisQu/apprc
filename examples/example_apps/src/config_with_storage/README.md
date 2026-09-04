# Config With Storage Example

`config_with_storage` demonstrates the normal storage-capable declaration:
`rc.AppRC(..., storage=rc.Storage(...))`. Its selector environment variable is
`APPRC_EXAMPLE_STORAGE_STORAGE`, which accepts a registered name or a path.

Start a clean session:

```bash
apprc-examples-lab config-with-storage
```

The printed walkthrough covers setup, the required secret, runtime, and the
registry:

```bash
apprc-config-with-storage config setup --storage-root PATH --yes
apprc-config-with-storage --storage default config set api_token lab-secret --scope storage
apprc-config-with-storage run
apprc-config-with-storage config storage list
```

Try both selector forms:

```bash
apprc-config-with-storage --storage default run
apprc-config-with-storage --storage PATH run
```

The generated registry also exposes `add`, `select`, `rename`, `repoint`,
`move`, and `remove`. `repoint` changes only `apprc.toml`; `move` transfers the
actual directory and then updates the registry.

Copy [`cli.py`](cli.py) and the [`config`](config) package for the common
storage-backed integration.

See the [example inventory](../../README.md#example-inventory) and
[storage command reference](../../../../docs/References.md#generated-cli-commands).
