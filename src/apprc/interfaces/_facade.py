"""Lazy facade for user-facing terminal integration APIs."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_CLI_EXPORTS = [
    "RuntimeIndependentCommand",
    "CliArgvProvider",
    "CliRuntimeContext",
    "CliRuntimeOptions",
    "CliRuntimeOptionsProtocol",
    "ConfigRuntimePolicy",
    "CliRuntime",
    "CliRuntimeSession",
    "ConfigCliState",
    "CliRuntimeStateFactory",
    "ConfigSelectorContext",
    "DefaultConfigCliState",
    "CliRuntimePolicy",
    "MountCliRuntimeStateFactory",
    "bootstrap_cli_env",
    "cli_options_from",
    "mount_config_cli",
    "parse_log_level",
]
_TUI_EXPORTS = [
    "ConfigEditorApp",
    "ConfigSetupApp",
]

_SYMBOL_EXPORTS = {
    **{name: "apprc.interfaces.cli" for name in _CLI_EXPORTS},
    **{name: "apprc.interfaces.tui" for name in _TUI_EXPORTS},
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.interfaces",
    all_exports=[
        *_CLI_EXPORTS,
        *_TUI_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
