"""User-facing CLI and TUI control surfaces."""

# ruff: noqa: F401

from typing import TYPE_CHECKING

from apprc.interfaces._facade import __all__ as __all__
from apprc.interfaces._facade import __dir__ as __dir__
from apprc.interfaces._facade import __getattr__ as __getattr__

if TYPE_CHECKING:
    from apprc.interfaces.cli import (
        RuntimeIndependentCommand,
        CliArgvProvider,
        CliRuntimeContext,
        CliRuntimeOptions,
        CliRuntimeOptionsProtocol,
        ConfigRuntimePolicy,
        CliRuntime,
        CliRuntimeSession,
        ConfigCliState,
        CliRuntimeStateFactory,
        ConfigSelectorContext,
        DefaultConfigCliState,
        CliRuntimePolicy,
        MountCliRuntimeStateFactory,
        bootstrap_cli_env,
        cli_options_from,
        mount_config_cli,
        parse_log_level,
    )
    from apprc.interfaces.tui import ConfigEditorApp, ConfigSetupApp
