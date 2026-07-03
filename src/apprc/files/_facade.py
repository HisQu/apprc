"""Lazy facade for public AppRC file and dotenv helpers."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_APP_HOME_EXPORTS = [
    "AppConfigHome",
    "ConfigHomeError",
    "app_config_file",
    "app_config_home",
    "ensure_text_file",
    "resolve_app_config_home",
    "resolve_package_root",
    "write_text_atomic",
]
_ENV_FILE_EXPORTS = [
    "EnvFileUpdate",
    "clear_env_file_value",
    "clear_storage_env_value",
    "ensure_env_file",
    "ensure_storage_env_file",
    "normalize_env_value",
    "read_env_file",
    "set_env_file_value",
    "set_storage_env_value",
    "storage_env_path",
    "write_env_file",
]
_SETUP_EXPORTS = [
    "ConfigSetupError",
    "ConfigSetupFlow",
    "ConfigSetupResult",
]

_SYMBOL_EXPORTS = {
    **{
        name: "apprc.user_files.app_home._package_resources"
        for name in ["resolve_package_root"]
    },
    **{
        name: "apprc.user_files.app_home.locations"
        for name in [
            "AppConfigHome",
            "ConfigHomeError",
            "app_config_file",
            "app_config_home",
            "ensure_text_file",
            "resolve_app_config_home",
            "write_text_atomic",
        ]
    },
    **{
        name: "apprc.user_files.env_files.files"
        for name in [
            "ensure_env_file",
            "ensure_storage_env_file",
            "read_env_file",
            "storage_env_path",
            "write_env_file",
        ]
    },
    **{
        name: "apprc.user_files.env_files.updates"
        for name in [
            "EnvFileUpdate",
            "clear_env_file_value",
            "clear_storage_env_value",
            "set_env_file_value",
            "set_storage_env_value",
        ]
    },
    **{
        name: "apprc.user_files.env_files.values"
        for name in ["normalize_env_value"]
    },
    **{name: "apprc.user_files.setup.flow" for name in _SETUP_EXPORTS},
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.files",
    all_exports=[
        *_APP_HOME_EXPORTS,
        *_ENV_FILE_EXPORTS,
        *_SETUP_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
