"""Typed surface for the lazy AppRC CLI integration namespace."""

# ruff: noqa: F401

from apprc.interfaces.cli import (
    COMMON_CLI_FLAG_OPTIONS as COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS as COMMON_CLI_VALUE_OPTIONS,
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS as DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
    MISSING_ACTION_MESSAGE as MISSING_ACTION_MESSAGE,
    RuntimeIndependentCommand as RuntimeIndependentCommand,
    CliArgvProvider as CliArgvProvider,
    CliRuntime as CliRuntime,
    CliRuntimeContext as CliRuntimeContext,
    CliRuntimeOptions as CliRuntimeOptions,
    CliRuntimeOptionsProtocol as CliRuntimeOptionsProtocol,
    CliRuntimePolicy as CliRuntimePolicy,
    CliRuntimeSession as CliRuntimeSession,
    CliRuntimeStateFactory as CliRuntimeStateFactory,
    ConfigCliState as ConfigCliState,
    ConfigRuntimePolicy as ConfigRuntimePolicy,
    ConfigSelectorContext as ConfigSelectorContext,
    DefaultConfigCliState as DefaultConfigCliState,
    EnvFileOverridesOption as EnvFileOverridesOption,
    EnvFilesOption as EnvFilesOption,
    LogLevelOption as LogLevelOption,
    MountCliRuntimeStateFactory as MountCliRuntimeStateFactory,
    SkipDotenvLayersOption as SkipDotenvLayersOption,
    StorageOption as StorageOption,
    active_storage_root_from_state as active_storage_root_from_state,
    args_after_command as args_after_command,
    bootstrap_cli_env as bootstrap_cli_env,
    bootstrap_cli_options as bootstrap_cli_options,
    build_config_doctor_payload as build_config_doctor_payload,
    build_config_typer_app as build_config_typer_app,
    cli_options_from as cli_options_from,
    cli_runtime_context_from as cli_runtime_context_from,
    cli_runtime_options_to_args as cli_runtime_options_to_args,
    config_command_text as config_command_text,
    config_request_skips_runtime as config_request_skips_runtime,
    config_setup_message as config_setup_message,
    dump_json as dump_json,
    ensure_config_group_name_available as ensure_config_group_name_available,
    exit_missing_action as exit_missing_action,
    initial_storage_from_state as initial_storage_from_state,
    mount_config_cli as mount_config_cli,
    parse_log_level as parse_log_level,
    prepare_cli_runtime_context as prepare_cli_runtime_context,
    print_config_doctor as print_config_doctor,
    print_config_paths as print_config_paths,
    run_typer_app as run_typer_app,
    state_from as state_from,
    strip_leading_options as strip_leading_options,
)
from apprc.interfaces.tui import (
    ConfigEditorApp as ConfigEditorApp,
    ConfigSetupApp as ConfigSetupApp,
)
from apprc.runtime.diagnostics import (
    ConfigDoctorPayload as ConfigDoctorPayload,
    ConfigDoctorStatus as ConfigDoctorStatus,
)
from apprc.runtime.result import (
    BootstrapLogger as BootstrapLogger,
    EnvBootstrapResult as EnvBootstrapResult,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
