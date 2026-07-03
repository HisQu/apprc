"""Advanced AppRC CLI integration namespace."""

# ruff: noqa: F401

from typing import TYPE_CHECKING

from apprc.cli._facade import __all__ as __all__
from apprc.cli._facade import __dir__ as __dir__
from apprc.cli._facade import __getattr__ as __getattr__

if TYPE_CHECKING:
    from apprc.interfaces.cli import (
        COMMON_CLI_FLAG_OPTIONS,
        COMMON_CLI_VALUE_OPTIONS,
        DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
        MISSING_ACTION_MESSAGE,
        RuntimeIndependentCommand,
        CliArgvProvider,
        CliRuntime,
        CliRuntimeContext,
        CliRuntimeOptions,
        CliRuntimeOptionsProtocol,
        CliRuntimePolicy,
        CliRuntimeSession,
        CliRuntimeStateFactory,
        ConfigCliState,
        ConfigRuntimePolicy,
        ConfigSelectorContext,
        DefaultConfigCliState,
        EnvFileOverridesOption,
        EnvFilesOption,
        LogLevelOption,
        MountCliRuntimeStateFactory,
        SkipDotenvLayersOption,
        StorageOption,
        active_storage_root_from_state,
        args_after_command,
        bootstrap_cli_env,
        bootstrap_cli_options,
        build_config_doctor_payload,
        build_config_typer_app,
        cli_options_from,
        cli_runtime_context_from,
        cli_runtime_options_to_args,
        config_command_text,
        config_request_skips_runtime,
        config_setup_message,
        dump_json,
        ensure_config_group_name_available,
        exit_missing_action,
        initial_storage_from_state,
        mount_config_cli,
        parse_log_level,
        prepare_cli_runtime_context,
        print_config_doctor,
        print_config_paths,
        run_typer_app,
        state_from,
        strip_leading_options,
    )
    from apprc.interfaces.tui import ConfigEditorApp, ConfigSetupApp
    from apprc.runtime.diagnostics import (
        ConfigDoctorPayload,
        ConfigDoctorStatus,
    )
    from apprc.runtime.result import BootstrapLogger, EnvBootstrapResult
