"""Lazy public facade for :mod:`apprc.logging`."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_ALL_EXPORTS = [
    "AppLogger",
    "HaiuLogger",
    "AppConsoleRenderer",
    "HaiuConsoleRenderer",
    "LoggingConfig",
    "LoggingRenderer",
    "async_telemetry",
    "forward_cli_output",
    "get_logger",
    "install_app_logger_class",
    "install_haiu_logger_class",
    "log_init_lifecycle",
    "new_cid",
    "set_cid",
    "setup_logging",
    "with_async_telemetry",
]

_SYMBOL_EXPORTS = {
    "AppLogger": "apprc.logging.core",
    "HaiuLogger": "apprc.logging.core",
    "AppConsoleRenderer": "apprc.logging.formats",
    "HaiuConsoleRenderer": "apprc.logging.formats",
    "LoggingConfig": "apprc.logging.config",
    "LoggingRenderer": "apprc.logging.config",
    "async_telemetry": "apprc.logging.functions",
    "forward_cli_output": "apprc.logging.subprocess",
    "get_logger": "apprc.logging.core",
    "install_app_logger_class": "apprc.logging.core",
    "install_haiu_logger_class": "apprc.logging.core",
    "log_init_lifecycle": "apprc.logging.functions",
    "new_cid": "apprc.logging.context",
    "set_cid": "apprc.logging.context",
    "setup_logging": "apprc.logging.config",
    "with_async_telemetry": "apprc.logging.functions",
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.logging",
    all_exports=_ALL_EXPORTS,
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
