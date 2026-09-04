# Config Only Example

`config_only` is the smallest example. Its Python declaration omits
`storage=rc.Storage()`, so no `--storage`, storage scope, or storage management
commands exist.

Start a clean session:

```bash
apprc-examples-lab config-only
```

The lab prints these core steps with its concrete temporary paths:

```bash
apprc-config-only config paths
apprc-config-only config setup --yes
apprc-config-only config set profile lab --scope user
apprc-config-only run
apprc-config-only config doctor
```

Setup creates only `apprc.user.env` in the relocated AppRC directory. The app
also demonstrates the packaged `config/apprc.defaults.env` layer and a typed
boolean field.

Copy [`cli.py`](cli.py) and the [`config`](config) package shape when an app
needs configuration but owns no persistent storage through AppRC.

See the [example inventory](../../README.md#example-inventory) and
[integration guide](../../../../docs/How-To-User-Guides.md#integrate-apprc).
