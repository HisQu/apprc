"""Typed surface for the lazy AppRC storage helper namespace."""

# ruff: noqa: F401

from apprc.user_files.storage_roots._io import (
    load_storage_registry_or_empty as load_storage_registry_or_empty,
    ordered_storage_names as ordered_storage_names,
    render_storage_registry as render_storage_registry,
    write_storage_registry as write_storage_registry,
)
from apprc.user_files.storage_roots._loading import (
    MissingStorageRegistryError as MissingStorageRegistryError,
    StorageRegistryInspection as StorageRegistryInspection,
    apprc_toml_path_for_create as apprc_toml_path_for_create,
    inspect_storage_registry as inspect_storage_registry,
    load_create_or_empty_storage_registry as load_create_or_empty_storage_registry,
    load_existing_storage_registry as load_existing_storage_registry,
    load_optional_runtime_storage_registry as load_optional_runtime_storage_registry,
    load_runtime_storage_registry_for_selector as load_runtime_storage_registry_for_selector,
)
from apprc.user_files.storage_roots._naming import (
    app_data_dir as app_data_dir,
    suggested_storage_name as suggested_storage_name,
    suggested_storage_root as suggested_storage_root,
)
from apprc.user_files.storage_roots.archive import (
    ARCHIVE_SUFFIX as ARCHIVE_SUFFIX,
    ProgressCallback as ProgressCallback,
    StorageArchiveProgress as StorageArchiveProgress,
    archive_directory as archive_directory,
    extract_archive as extract_archive,
    is_storage_archive_path as is_storage_archive_path,
    storage_archive_default_path as storage_archive_default_path,
    storage_root_name_from_archive as storage_root_name_from_archive,
)
from apprc.user_files.storage_roots.model import (
    ArchivedStorageRecord as ArchivedStorageRecord,
    StorageRecord as StorageRecord,
    StorageRegistry as StorageRegistry,
)
from apprc.user_files.storage_roots.move import (
    StorageMoveError as StorageMoveError,
    StorageMoveResult as StorageMoveResult,
    move_storage as move_storage,
)
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError as StorageRootPathError,
    normalize_storage_root_path as normalize_storage_root_path,
    windows_drive_path_to_posix as windows_drive_path_to_posix,
)
from apprc.user_files.storage_roots.registry import (
    prune_missing_archived_storages as prune_missing_archived_storages,
    record_archived_storage as record_archived_storage,
    register_storage as register_storage,
    rename_storage as rename_storage,
    repoint_storage as repoint_storage,
    remove_archived_storage as remove_archived_storage,
    select_storage as select_storage,
    unregister_storage as unregister_storage,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelection as StorageSelection,
    StorageSelectorError as StorageSelectorError,
    missing_storage_selector_error as missing_storage_selector_error,
    resolve_active_storage_selection as resolve_active_storage_selection,
    resolve_registered_storage_name as resolve_registered_storage_name,
    resolve_storage_selector_value as resolve_storage_selector_value,
)

__all__: list[str]

def __getattr__(name: str) -> object: ...
def __dir__() -> list[str]: ...
