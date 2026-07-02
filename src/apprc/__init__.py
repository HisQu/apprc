"""Friendly public facade for AppRC.

Application code should import AppRC once with ``import apprc`` and access the
public API through that handle.
"""

# ruff: noqa: F401

from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config.base import BaseConfig
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import (
    config_owner_for,
    env_field,
    env_owner,
)
from apprc.definition.env_config.lookup import (
    find_field_by_config_path,
    find_field_by_env_key,
    iter_config_fields,
    resolve_config_field_reference,
)
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.env_config.sentinels import (
    CONFIG_MISSING,
    ENV_FIELD_MISSING,
)
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
from apprc.interfaces.cli.runtime import (
    RuntimeIndependentCommand,
    CliArgvProvider,
    CliRuntime,
    CliRuntimeSession,
    CliRuntimeStateFactory,
    CliRuntimePolicy,
    MountCliRuntimeStateFactory,
    ensure_config_group_name_available,
)
from apprc.interfaces.cli.config_command import (
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
    active_storage_root_from_state,
    build_config_typer_app,
    config_request_skips_runtime,
    initial_storage_from_state,
)
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
)
from apprc.interfaces.cli.config_command.state import (
    ConfigRuntimePolicy,
    ConfigCliState,
    DefaultConfigCliState,
)
from apprc.interfaces.cli.context import (
    CliRuntimeContext,
    CliRuntimeOptions,
    CliRuntimeOptionsProtocol,
    cli_options_from,
    cli_runtime_context_from,
    cli_runtime_options_to_args,
    bootstrap_cli_options,
    prepare_cli_runtime_context,
)
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)
from apprc.interfaces.cli.mount import mount_config_cli
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
    EnvFileOverridesOption,
    EnvFilesOption,
    LogLevelOption,
    SkipDotenvLayersOption,
    StorageOption,
)
from apprc.interfaces.tui.editor.app import ConfigEditorApp
from apprc.interfaces.tui.setup.app import ConfigSetupApp
from apprc.runtime.bootstrap import bootstrap_env
from apprc.runtime.diagnostics.payload import (
    ConfigDoctorPayload,
    build_config_doctor_payload,
)
from apprc.runtime.diagnostics.messages import (
    config_command_text,
    config_setup_message,
)
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.runtime.provenance import (
    ConfigOriginState,
    ConfigProvenance,
    ConfigProvenanceOrigin,
    ConfigProvenanceSource,
    EnvValueOrigin,
    PythonProvenanceOrigin,
    ShellProvenanceOrigin,
    base_config_provenance_of,
    constructor_field_origins,
    env_value_origin,
    provenance,
    provenance_of,
    provenance_origin_label,
    public_config_fields,
    register_env_value_origins,
    set_field_origin,
    shell_origin_for_env_value,
    source_for_origin,
    with_field_origin,
)
from apprc.runtime.result import BootstrapLogger, EnvBootstrapResult
from apprc.user_files.app_home._package_resources import resolve_package_root
from apprc.user_files.app_home.locations import (
    AppConfigHome,
    ConfigHomeError,
    app_config_file,
    app_config_home,
    ensure_text_file,
    resolve_app_config_home,
    write_text_atomic,
)
from apprc.user_files.env_files.files import (
    ensure_env_file,
    ensure_storage_env_file,
    read_env_file,
    storage_env_path,
    write_env_file,
)
from apprc.user_files.env_files.updates import (
    EnvFileUpdate,
    clear_env_file_value,
    clear_storage_env_value,
    set_env_file_value,
    set_storage_env_value,
)
from apprc.user_files.env_files.values import normalize_env_value
from apprc.user_files.setup.flow import (
    ConfigSetupError,
    ConfigSetupFlow,
    ConfigSetupResult,
)
from apprc.user_files.storage_roots.model import (
    ArchivedStorageRecord,
    StorageRecord,
    StorageRegistry,
)
from apprc.user_files.storage_roots.registry import (
    prune_missing_archived_storages,
    record_archived_storage,
    register_storage,
    remove_archived_storage,
    unregister_storage,
)
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty
from apprc.user_files.storage_roots._naming import (
    suggested_storage_name,
    suggested_storage_root,
)
from apprc.utils import (
    deep_get,
    deep_right_merge,
    deep_set,
    timer,
)

__all__ = [
    "CONFIG_MISSING",
    "ENV_FIELD_MISSING",
    "AppConfigHome",
    "AppConfigKit",
    "AppConfigSpec",
    "ArchivedStorageRecord",
    "BaseConfig",
    "BootstrapLogger",
    "RuntimeIndependentCommand",
    "COMMON_CLI_FLAG_OPTIONS",
    "COMMON_CLI_VALUE_OPTIONS",
    "CapabilityState",
    "CliArgvProvider",
    "CliRuntimeContext",
    "CliRuntimeOptions",
    "CliRuntimeOptionsProtocol",
    "ConfigRuntimePolicy",
    "CliRuntime",
    "CliRuntimeSession",
    "ConfigCliState",
    "CliRuntimeStateFactory",
    "ConfigDoctorPayload",
    "ConfigDoctorStatus",
    "ConfigEditorApp",
    "ConfigField",
    "ConfigHomeError",
    "ConfigOriginState",
    "ConfigOwner",
    "ConfigProvenance",
    "ConfigProvenanceOrigin",
    "ConfigProvenanceSource",
    "ConfigSelectorContext",
    "ConfigSetupApp",
    "ConfigSetupError",
    "ConfigSetupFlow",
    "ConfigSetupResult",
    "DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS",
    "DefaultConfigCliState",
    "EnvBootstrapResult",
    "EnvConfig",
    "EnvFileUpdate",
    "EnvFileOverridesOption",
    "EnvFilesOption",
    "EnvValueOrigin",
    "CliRuntimePolicy",
    "LogLevelOption",
    "MISSING_ACTION_MESSAGE",
    "MountCliRuntimeStateFactory",
    "PythonProvenanceOrigin",
    "ShellProvenanceOrigin",
    "SkipDotenvLayersOption",
    "StorageLayerState",
    "StorageOption",
    "StorageRecord",
    "StorageRegistry",
    "active_storage_root_from_state",
    "app_config_file",
    "app_config_home",
    "cli_options_from",
    "cli_runtime_context_from",
    "cli_runtime_options_to_args",
    "args_after_command",
    "base_config_provenance_of",
    "bootstrap_cli_env",
    "bootstrap_cli_options",
    "bootstrap_env",
    "build_config_doctor_payload",
    "build_config_typer_app",
    "clear_env_file_value",
    "clear_storage_env_value",
    "config_command_text",
    "config_owner_for",
    "config_request_skips_runtime",
    "config_setup_message",
    "constructor_field_origins",
    "deep_get",
    "deep_right_merge",
    "deep_set",
    "dump_json",
    "ensure_config_group_name_available",
    "env_field",
    "env_owner",
    "env_value_origin",
    "ensure_env_file",
    "ensure_storage_env_file",
    "ensure_text_file",
    "exit_missing_action",
    "find_field_by_config_path",
    "find_field_by_env_key",
    "initial_storage_from_state",
    "iter_config_fields",
    "load_storage_registry_or_empty",
    "mount_config_cli",
    "normalize_env_value",
    "parse_log_level",
    "prepare_cli_runtime_context",
    "print_config_doctor",
    "print_config_paths",
    "provenance",
    "provenance_of",
    "provenance_origin_label",
    "prune_missing_archived_storages",
    "public_config_fields",
    "read_env_file",
    "record_archived_storage",
    "register_env_value_origins",
    "register_storage",
    "remove_archived_storage",
    "resolve_app_config_home",
    "resolve_config_field_reference",
    "resolve_package_root",
    "set_env_file_value",
    "set_field_origin",
    "set_storage_env_value",
    "shell_origin_for_env_value",
    "source_for_origin",
    "storage_env_path",
    "run_typer_app",
    "state_from",
    "strip_leading_options",
    "suggested_storage_name",
    "suggested_storage_root",
    "timer",
    "unregister_storage",
    "with_field_origin",
    "write_env_file",
    "write_text_atomic",
]
