# Importable client example

This package shows a library that owns its configuration. Code using the
library imports `LibraryClient` and constructs it without declaring AppRC or
calling a setup function:

```python
from library_client import LibraryClient

print(LibraryClient().request_timeout)
```

The [client implementation](client.py) resolves settings on construction. The
[config section](config/sections/client.py) has a Python timeout fallback of
`30`, while the [packaged defaults](config/apprc.defaults.env) set it to `20`.
An existing `apprc.user.env` can override that value, and the process environment
can override both. Importing the package does not read or write managed files.

The separate [config CLI](cli.py) lets users create and edit the user dotenv.
From an AppRC checkout with the example package installed, run:

```shell
apprc-examples-lab library-client
```

Inside the disposable lab, run:

```shell
apprc-library-client run
apprc-library-client config setup --yes
apprc-library-client config set request_timeout 15 --scope user
apprc-library-client run
python -c 'from library_client import LibraryClient; print(LibraryClient().request_timeout)'
```

The first `run` reports `20`; the final two commands report `15`. The setup
command creates `apprc.user.env` inside the lab's temporary AppRC directory.
The client constructor itself writes nothing. See the independent
[importable-client guide](../../../../docs/How-To-User-Guides.md#use-apprc-inside-an-importable-client)
for all files needed to reproduce the pattern outside this example package.
