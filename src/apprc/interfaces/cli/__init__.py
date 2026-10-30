"""Reusable CLI helpers for application config commands."""

# ruff: noqa: F401

from apprc.interfaces.cli._resolution import parse_log_level, resolve_cli_config
from apprc.interfaces.cli._typer_utils import (
    MISSING_ACTION_MESSAGE,
    args_after_command,
    dump_json,
    exit_missing_action,
    run_typer_app,
    state_from,
    strip_leading_options,
)
from apprc.interfaces.cli.config_command import (
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
    ConfigCliState,
    ConfigRuntimePolicy,
    ConfigSelectorContext,
    DefaultConfigCliState,
    active_workspace_root_from_state,
    build_config_typer_app,
    config_request_skips_runtime,
    initial_workspace_from_state,
)
from apprc.interfaces.cli.context import (
    CliRuntimeContext,
    CliRuntimeOptions,
    CliRuntimeOptionsProtocol,
    InstallationCommandContext,
    cli_options_from,
    cli_runtime_context_from,
    cli_runtime_options_to_args,
    installation_command_context_from,
    prepare_cli_runtime_context,
    prepare_installation_command_context,
    resolve_cli_options,
)
from apprc.interfaces.cli.diagnostics.messages import (
    config_command_text,
    config_setup_message,
)
from apprc.interfaces.cli.diagnostics.payload import build_config_doctor_payload
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)
from apprc.interfaces.cli.mount import mount_app_cli
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
    AppRootOption,
    EnvFileOverridesOption,
    EnvFilesOption,
    LayoutOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    WorkspaceOption,
)
from apprc.interfaces.cli.runtime import (
    CliArgvProvider,
    CliRuntime,
    CliRuntimePolicy,
    CliRuntimeSession,
    CliRuntimeStateFactory,
    MountCliRuntimeStateFactory,
    RuntimeIndependentCommand,
    ensure_config_group_name_available,
)
