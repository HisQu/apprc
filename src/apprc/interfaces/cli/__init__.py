"""Reusable CLI helpers for application config commands."""

# ruff: noqa: F401

from apprc.interfaces.cli._bootstrap import bootstrap_cli_env, parse_log_level
from apprc.interfaces.cli._typer_utils import (
    MISSING_ACTION_MESSAGE,
    args_after_command,
    dump_json,
    exit_missing_action,
    run_typer_app,
    state_from,
    strip_leading_options,
)
from apprc.interfaces.cli.bridge import (
    BootstraplessCommand,
    CliArgvProvider,
    ConfigCliBridge,
    ConfigCliSession,
    ConfigCliStateFactory,
    HostCliBootstrapPolicy,
    MountConfigCliStateFactory,
    ensure_config_group_name_available,
)
from apprc.interfaces.cli.config_command import (
    DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS,
    ConfigBootstrapPolicy,
    ConfigCliState,
    ConfigSelectorContext,
    DefaultConfigCliState,
    active_storage_root_from_state,
    build_config_typer_app,
    config_request_skips_runtime_bootstrap,
    initial_storage_from_state,
)
from apprc.interfaces.cli.context import (
    CliBootstrapContext,
    CliBootstrapOptions,
    CliBootstrapOptionsProtocol,
    apprc_context_from,
    apprc_options_to_args,
    bootstrap_cli_options,
    prepare_typer_context,
)
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)
from apprc.interfaces.cli.mount import mount_config_cli
from apprc.interfaces.cli.options import (
    COMMON_HOST_FLAG_OPTIONS,
    COMMON_HOST_VALUE_OPTIONS,
    EnvFileOverridesOption,
    EnvFilesOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
)
from apprc.runtime.diagnostics.messages import (
    config_command_text,
    config_setup_message,
)
from apprc.runtime.diagnostics.payload import build_config_doctor_payload

__all__ = [
    "COMMON_HOST_FLAG_OPTIONS",
    "COMMON_HOST_VALUE_OPTIONS",
    "DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS",
    "BootstraplessCommand",
    "CliArgvProvider",
    "CliBootstrapContext",
    "CliBootstrapOptions",
    "CliBootstrapOptionsProtocol",
    "ConfigBootstrapPolicy",
    "ConfigCliBridge",
    "ConfigCliSession",
    "ConfigCliState",
    "ConfigCliStateFactory",
    "ConfigSelectorContext",
    "DefaultConfigCliState",
    "EnvFileOverridesOption",
    "EnvFilesOption",
    "HostCliBootstrapPolicy",
    "LogLevelOption",
    "MISSING_ACTION_MESSAGE",
    "MountConfigCliStateFactory",
    "SkipDotenvLayersOption",
    "StorageOption",
    "active_storage_root_from_state",
    "apprc_context_from",
    "apprc_options_to_args",
    "args_after_command",
    "bootstrap_cli_env",
    "bootstrap_cli_options",
    "build_config_doctor_payload",
    "build_config_typer_app",
    "config_command_text",
    "config_request_skips_runtime_bootstrap",
    "config_setup_message",
    "dump_json",
    "ensure_config_group_name_available",
    "exit_missing_action",
    "initial_storage_from_state",
    "mount_config_cli",
    "parse_log_level",
    "prepare_typer_context",
    "print_config_doctor",
    "print_config_paths",
    "run_typer_app",
    "state_from",
    "strip_leading_options",
]
