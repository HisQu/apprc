"""Typed surface for the lazy AppRC terminal integration namespace."""

# ruff: noqa: F401

from apprc.interfaces.cli import (
    RuntimeIndependentCommand as RuntimeIndependentCommand,
    CliArgvProvider as CliArgvProvider,
    CliRuntimeContext as CliRuntimeContext,
    CliRuntimeOptions as CliRuntimeOptions,
    CliRuntimeOptionsProtocol as CliRuntimeOptionsProtocol,
    ConfigRuntimePolicy as ConfigRuntimePolicy,
    CliRuntime as CliRuntime,
    CliRuntimeSession as CliRuntimeSession,
    ConfigCliState as ConfigCliState,
    CliRuntimeStateFactory as CliRuntimeStateFactory,
    ConfigSelectorContext as ConfigSelectorContext,
    DefaultConfigCliState as DefaultConfigCliState,
    CliRuntimePolicy as CliRuntimePolicy,
    MountCliRuntimeStateFactory as MountCliRuntimeStateFactory,
    bootstrap_cli_env as bootstrap_cli_env,
    cli_options_from as cli_options_from,
    mount_config_cli as mount_config_cli,
    parse_log_level as parse_log_level,
)
from apprc.interfaces.tui import (
    ConfigEditorApp as ConfigEditorApp,
    ConfigSetupApp as ConfigSetupApp,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
