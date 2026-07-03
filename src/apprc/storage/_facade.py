"""Lazy facade for public AppRC storage-root helpers."""

from __future__ import annotations

from apprc._lazy import build_lazy_facade

_ARCHIVE_EXPORTS = [
    "ARCHIVE_SUFFIX",
    "ProgressCallback",
    "StorageArchiveProgress",
    "archive_directory",
    "extract_archive",
    "is_storage_archive_path",
    "storage_archive_default_path",
    "storage_root_name_from_archive",
]
_IO_EXPORTS = [
    "load_storage_registry_or_empty",
    "ordered_storage_names",
    "write_storage_registry",
]
_LOADING_EXPORTS = [
    "StorageRegistryInspection",
    "index_path_for_create",
    "inspect_storage_registry",
    "load_create_or_empty_storage_registry",
    "load_existing_storage_registry",
    "load_optional_runtime_storage_registry",
    "load_runtime_storage_registry_for_selector",
]
_MODEL_EXPORTS = [
    "ArchivedStorageRecord",
    "StorageRecord",
    "StorageRegistry",
]
_NAMING_EXPORTS = [
    "app_data_dir",
    "suggested_storage_name",
    "suggested_storage_root",
]
_PATH_EXPORTS = [
    "StorageRootPathError",
    "normalize_storage_root_path",
    "windows_drive_path_to_posix",
]
_REGISTRY_EXPORTS = [
    "prune_missing_archived_storages",
    "record_archived_storage",
    "register_storage",
    "remove_archived_storage",
    "unregister_storage",
]
_SELECTOR_EXPORTS = [
    "StorageSelection",
    "StorageSelectorError",
    "missing_storage_selector_error",
    "resolve_active_storage_selection",
    "resolve_registered_storage_name",
    "resolve_setup_storage_root_from_env",
    "resolve_storage_selector_value",
]

_SYMBOL_EXPORTS = {
    **{
        name: "apprc.user_files.storage_roots.archive"
        for name in _ARCHIVE_EXPORTS
    },
    **{name: "apprc.user_files.storage_roots._io" for name in _IO_EXPORTS},
    **{
        name: "apprc.user_files.storage_roots._loading"
        for name in _LOADING_EXPORTS
    },
    **{name: "apprc.user_files.storage_roots.model" for name in _MODEL_EXPORTS},
    **{
        name: "apprc.user_files.storage_roots._naming"
        for name in _NAMING_EXPORTS
    },
    **{name: "apprc.user_files.storage_roots.paths" for name in _PATH_EXPORTS},
    **{
        name: "apprc.user_files.storage_roots.registry"
        for name in _REGISTRY_EXPORTS
    },
    **{
        name: "apprc.user_files.storage_roots.selector"
        for name in _SELECTOR_EXPORTS
    },
}

__all__, __getattr__, __dir__ = build_lazy_facade(
    public_module="apprc.storage",
    all_exports=[
        *_ARCHIVE_EXPORTS,
        *_IO_EXPORTS,
        *_LOADING_EXPORTS,
        *_MODEL_EXPORTS,
        *_NAMING_EXPORTS,
        *_PATH_EXPORTS,
        *_REGISTRY_EXPORTS,
        *_SELECTOR_EXPORTS,
    ],
    module_exports={},
    symbol_exports=_SYMBOL_EXPORTS,
)
