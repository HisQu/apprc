"""Lazy facade for advanced AppRC CLI integration APIs."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_CLI_EXPORTS = [
    "COMMON_CLI_FLAG_OPTIONS",
    "COMMON_CLI_VALUE_OPTIONS",
    "DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS",
    "MISSING_ACTION_MESSAGE",
    "RuntimeIndependentCommand",
    "CliArgvProvider",
    "CliRuntime",
    "CliRuntimeContext",
    "CliRuntimeOptions",
    "CliRuntimeOptionsProtocol",
    "CliRuntimePolicy",
    "CliRuntimeSession",
    "CliRuntimeStateFactory",
    "ConfigCliState",
    "ConfigRuntimePolicy",
    "ConfigSelectorContext",
    "DefaultConfigCliState",
    "EnvFileOverridesOption",
    "EnvFilesOption",
    "LogLevelOption",
    "MountCliRuntimeStateFactory",
    "SkipDotenvLayersOption",
    "StorageOption",
    "active_storage_root_from_state",
    "args_after_command",
    "bootstrap_cli_env",
    "bootstrap_cli_options",
    "build_config_doctor_payload",
    "build_config_typer_app",
    "cli_options_from",
    "cli_runtime_context_from",
    "cli_runtime_options_to_args",
    "config_command_text",
    "config_request_skips_runtime",
    "config_setup_message",
    "dump_json",
    "ensure_config_group_name_available",
    "exit_missing_action",
    "initial_storage_from_state",
    "mount_config_cli",
    "parse_log_level",
    "prepare_cli_runtime_context",
    "print_config_doctor",
    "print_config_paths",
    "run_typer_app",
    "state_from",
    "strip_leading_options",
]
_DIAGNOSTIC_EXPORTS = [
    "ConfigDoctorPayload",
    "ConfigDoctorStatus",
]
_RESULT_EXPORTS = [
    "BootstrapLogger",
    "EnvBootstrapResult",
]
_TUI_EXPORTS = [
    "ConfigEditorApp",
    "ConfigSetupApp",
]

_SYMBOL_EXPORTS = {
    **{name: "apprc.interfaces.cli" for name in _CLI_EXPORTS},
    **{name: "apprc.runtime.diagnostics" for name in _DIAGNOSTIC_EXPORTS},
    **{name: "apprc.runtime.result" for name in _RESULT_EXPORTS},
    **{name: "apprc.interfaces.tui" for name in _TUI_EXPORTS},
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.cli",
    all_exports=[
        *_CLI_EXPORTS,
        *_DIAGNOSTIC_EXPORTS,
        *_RESULT_EXPORTS,
        *_TUI_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
