"""Typed surface for the lazy AppRC CLI integration namespace."""

# ruff: noqa: F401

from apprc.interfaces.cli import (
    COMMON_CLI_FLAG_OPTIONS as COMMON_CLI_FLAG_OPTIONS,
)
from apprc.interfaces.cli import (
    COMMON_CLI_VALUE_OPTIONS as COMMON_CLI_VALUE_OPTIONS,
)
from apprc.interfaces.cli import (
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS as DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
)
from apprc.interfaces.cli import (
    MISSING_ACTION_MESSAGE as MISSING_ACTION_MESSAGE,
)
from apprc.interfaces.cli import (
    AppRootOption as AppRootOption,
)
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
    EnvFileOverridesOption as EnvFileOverridesOption,
)
from apprc.interfaces.cli import (
    EnvFilesOption as EnvFilesOption,
)
from apprc.interfaces.cli import (
    LayoutOption as LayoutOption,
)
from apprc.interfaces.cli import (
    LogLevelOption as LogLevelOption,
)
from apprc.interfaces.cli import (
    MountCliRuntimeStateFactory as MountCliRuntimeStateFactory,
)
from apprc.interfaces.cli import (
    RuntimeIndependentCommand as RuntimeIndependentCommand,
)
from apprc.interfaces.cli import (
    SkipDotenvLayersOption as SkipDotenvLayersOption,
)
from apprc.interfaces.cli import (
    WorkspaceOption as WorkspaceOption,
)
from apprc.interfaces.cli import (
    active_workspace_root_from_state as active_workspace_root_from_state,
)
from apprc.interfaces.cli import (
    args_after_command as args_after_command,
)
from apprc.interfaces.cli import (
    build_config_doctor_payload as build_config_doctor_payload,
)
from apprc.interfaces.cli import (
    build_config_typer_app as build_config_typer_app,
)
from apprc.interfaces.cli import (
    cli_options_from as cli_options_from,
)
from apprc.interfaces.cli import (
    cli_runtime_context_from as cli_runtime_context_from,
)
from apprc.interfaces.cli import (
    cli_runtime_options_to_args as cli_runtime_options_to_args,
)
from apprc.interfaces.cli import (
    config_command_text as config_command_text,
)
from apprc.interfaces.cli import (
    config_request_skips_runtime as config_request_skips_runtime,
)
from apprc.interfaces.cli import (
    config_setup_message as config_setup_message,
)
from apprc.interfaces.cli import (
    dump_json as dump_json,
)
from apprc.interfaces.cli import (
    ensure_config_group_name_available as ensure_config_group_name_available,
)
from apprc.interfaces.cli import (
    exit_missing_action as exit_missing_action,
)
from apprc.interfaces.cli import (
    initial_workspace_from_state as initial_workspace_from_state,
)
from apprc.interfaces.cli import (
    mount_app_cli as mount_app_cli,
)
from apprc.interfaces.cli import (
    parse_log_level as parse_log_level,
)
from apprc.interfaces.cli import (
    prepare_cli_runtime_context as prepare_cli_runtime_context,
)
from apprc.interfaces.cli import (
    print_config_doctor as print_config_doctor,
)
from apprc.interfaces.cli import (
    print_config_paths as print_config_paths,
)
from apprc.interfaces.cli import (
    resolve_cli_config as resolve_cli_config,
)
from apprc.interfaces.cli import (
    resolve_cli_options as resolve_cli_options,
)
from apprc.interfaces.cli import (
    run_typer_app as run_typer_app,
)
from apprc.interfaces.cli import (
    state_from as state_from,
)
from apprc.interfaces.cli import (
    strip_leading_options as strip_leading_options,
)
from apprc.interfaces.cli.diagnostics import (
    ConfigDoctorPayload as ConfigDoctorPayload,
)
from apprc.interfaces.cli.diagnostics import (
    ConfigDoctorStatus as ConfigDoctorStatus,
)
from apprc.runtime.logging import ResolutionLogger as ResolutionLogger

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
