"""Lazy facade for AppRC-managed user files.

The aggregate user-file package is intentionally lazy because app config specs
import individual user-file modules during their own initialization.
"""

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
_STORAGE_EXPORTS = [
    "ArchivedStorageRecord",
    "StorageRecord",
    "StorageRegistry",
    "load_storage_registry_or_empty",
    "prune_missing_archived_storages",
    "record_archived_storage",
    "register_storage",
    "remove_archived_storage",
    "suggested_storage_name",
    "suggested_storage_root",
    "unregister_storage",
]

_SYMBOL_EXPORTS = {
    **{name: "apprc.user_files.app_home" for name in _APP_HOME_EXPORTS},
    **{name: "apprc.user_files.env_files" for name in _ENV_FILE_EXPORTS},
    **{name: "apprc.user_files.setup" for name in _SETUP_EXPORTS},
    **{name: "apprc.user_files.storage_roots" for name in _STORAGE_EXPORTS},
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.user_files",
    all_exports=[
        *_APP_HOME_EXPORTS,
        *_ENV_FILE_EXPORTS,
        *_SETUP_EXPORTS,
        *_STORAGE_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
