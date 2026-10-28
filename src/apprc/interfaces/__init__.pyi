"""Typed surface for the lazy AppRC terminal integration namespace."""

# ruff: noqa: F401

from apprc.interfaces.cli import (
    CliArgvProvider as CliArgvProvider,
)
from apprc.interfaces.cli import (
    CliRuntime as CliRuntime,
)
from apprc.interfaces.cli import (
    CliRuntimeContext as CliRuntimeContext,
)
from apprc.interfaces.cli import (
    CliRuntimeOptions as CliRuntimeOptions,
)
from apprc.interfaces.cli import (
    CliRuntimeOptionsProtocol as CliRuntimeOptionsProtocol,
)
from apprc.interfaces.cli import (
    CliRuntimePolicy as CliRuntimePolicy,
)
from apprc.interfaces.cli import (
    CliRuntimeSession as CliRuntimeSession,
)
from apprc.interfaces.cli import (
    CliRuntimeStateFactory as CliRuntimeStateFactory,
)
from apprc.interfaces.cli import (
    ConfigCliState as ConfigCliState,
)
from apprc.interfaces.cli import (
    ConfigRuntimePolicy as ConfigRuntimePolicy,
)
from apprc.interfaces.cli import (
    ConfigSelectorContext as ConfigSelectorContext,
)
from apprc.interfaces.cli import (
    DefaultConfigCliState as DefaultConfigCliState,
)
from apprc.interfaces.cli import (
    MountCliRuntimeStateFactory as MountCliRuntimeStateFactory,
)
from apprc.interfaces.cli import (
    RuntimeIndependentCommand as RuntimeIndependentCommand,
)
from apprc.interfaces.cli import (
    cli_options_from as cli_options_from,
)
from apprc.interfaces.cli import (
    mount_app_cli as mount_app_cli,
)
from apprc.interfaces.cli import (
    parse_log_level as parse_log_level,
)
from apprc.interfaces.cli import (
    resolve_cli_config as resolve_cli_config,
)
from apprc.interfaces.tui import (
    ConfigEditorApp as ConfigEditorApp,
)
from apprc.interfaces.tui import (
    ConfigSetupApp as ConfigSetupApp,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
