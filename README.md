
<!-- This is a comment -->

<!-- ============================================================== -->
<!-- == Header ==================================================== -->
<div align="center">

<!-- --- Title ---------------------------------------------------- -->
# `apprc`: Runtime Configs 


<!-- --- Logo ----------------------------------------------------- -->
*Part of:*

<a href="https://hisqu.de" target="_blank">
  <img 
  src="https://avatars.githubusercontent.com/u/196629600?s=200&v=4" 
  width="100px" alt="logo"
  style="margin-top: -10px;"> 
</a>

<br>

<!-- --- Badges --------------------------------------------------- -->
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pyright](https://img.shields.io/badge/type%20checked-pyright-blue)](https://microsoft.github.io/pyright/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC)](https://docs.pytest.org/)
<!-- [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/HisQu/haiu/blob/main/LICENSE) -->

</div>




<!-- --- URLs --------------------------------------------------- -->
[`direnv`]: https://direnv.net/
[`just`]: https://github.com/casey/just?tab=readme-ov-file#packages
[`uv`]: https://github.com/astral-sh/uv?tab=readme-ov-file#uv




Reusable application runtime configuration and logging helpers.

This package currently contains the config backend and stdlib/structlog logging
setup extracted from Haiu. Application packages provide their own config owner
catalog, packaged defaults, and CLI wiring.

### App Config Kit

Define an application's config contract once and let `apprc` derive the common
runtime workflows from it:

```python
from apprc import AppConfigKit

APP_CONFIG = AppConfigKit(
    app_name="myapp",
    display_name="MyApp",
    config_package="myapp.config",
    owners=ALL_CONFIG_OWNERS,
    storage_root_env_key="MYAPP_STORAGE",
    registry_filename="myapp.toml",
)

config_app = APP_CONFIG.typer_app(
    state_type=MyCliState,
    runtime_payload=build_config_payload,
)
```

The generated Typer app provides `config show`, `config doctor`,
`config init`, `config set-default`, `config set`, and `config edit`.

Config field specs can provide `explanation_short` for compact table displays
and `explanation_long` for the interactive editor modal. Existing
`explanation=` values are accepted as a compatibility shortcut.

### Lightweight Dependencies:
```toml
    "python-dotenv",       # < Loads .env files
    "typed-settings[dotenv]", # < Typed env/config binding
    "structlog",           # < Stdlib-backed structured logging
    "rich",                # < Exception rendering
    "textual",             # < Terminal config editor
    "typer",               # < Reusable config CLI builder
```
