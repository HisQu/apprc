# Cache-only example

This app declares `paths=rc.Paths(cache=True)` without a schema, configuration
bundle, or registry. AppRC initializes its cache paths on demand and exposes
grouped help without loading application settings.

```shell
apprc-cache-only --help
apprc-cache-only cache init
apprc-cache-only paths cache
```
