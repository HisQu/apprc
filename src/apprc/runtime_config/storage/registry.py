"""Operations for optional AppRC multi-storage registries."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import replace
from pathlib import Path

# == Internal ================================
from apprc.runtime_config.storage.io import (
    load_storage_registry_or_empty,
    ordered_storage_names,
    write_storage_registry,
)
from apprc.runtime_config.storage.local_env import ensure_local_env_file
from apprc.runtime_config.storage.model import (
    ArchivedStorageRecord,
    StorageRecord,
    StorageRegistry,
)
from apprc.runtime_config.storage.naming import (
    app_data_dir,
    suggested_storage_name,
    suggested_storage_root,
    validate_storage_name,
)
from apprc.runtime_config.storage.paths import normalize_storage_root_path

__all__ = [
    "ArchivedStorageRecord",
    "StorageRecord",
    "StorageRegistry",
    "app_data_dir",
    "load_storage_registry_or_empty",
    "ordered_storage_names",
    "prune_missing_archived_storages",
    "record_archived_storage",
    "register_storage",
    "remove_archived_storage",
    "suggested_storage_name",
    "suggested_storage_root",
    "unregister_storage",
    "write_storage_registry",
]


def register_storage(
    *,
    name: str,
    root: Path,
    path: Path,
    storage_env_filename: str = ".env.apprc-storage",
) -> StorageRegistry:
    """Add or update one storage entry and write the registry.

    :param name: Storage selector to create or update.
    :param root: Storage root directory.
    :param path: AppRC TOML location.
    :param storage_env_filename: Storage-local dotenv filename to create.
    :return: Updated registry.
    """
    validate_storage_name(name)
    resolved_root = normalize_storage_root_path(root).resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    ensure_local_env_file(resolved_root, filename=storage_env_filename)

    current = load_storage_registry_or_empty(path)
    storages = dict(current.storages)
    storages[name] = StorageRecord(name=name, root=resolved_root)

    updated = replace(
        current,
        storages=storages,
    )
    write_storage_registry(updated)
    return updated


def unregister_storage(
    *,
    name: str,
    path: Path,
) -> StorageRegistry:
    """Remove one live storage entry from the registry.

    :param name: Live storage selector to remove.
    :param path: AppRC TOML location.
    :return: Updated registry.
    :raises ValueError: If ``name`` is unknown.
    """
    validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    current.selected(name)
    storages = dict(current.storages)
    storages.pop(name)

    updated = replace(
        current,
        storages=storages,
    )
    write_storage_registry(updated)
    return updated


def record_archived_storage(
    *,
    name: str,
    archive: Path,
    source_root: Path,
    path: Path,
) -> StorageRegistry:
    """Remember the last archive path for one storage selector."""
    validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    archived_storages = dict(current.archived_storages)
    archived_storages[name] = ArchivedStorageRecord(
        name=name,
        archive=normalize_storage_root_path(archive).expanduser(),
        source_root=normalize_storage_root_path(source_root).expanduser(),
    )
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def remove_archived_storage(
    *,
    name: str,
    path: Path,
) -> StorageRegistry:
    """Remove one stale or restored archive convenience entry."""
    validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    archived_storages = dict(current.archived_storages)
    archived_storages.pop(name, None)
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def prune_missing_archived_storages(
    *,
    path: Path,
) -> StorageRegistry:
    """Drop archive records whose last known file no longer exists."""
    current = load_storage_registry_or_empty(path)
    archived_storages = {
        name: record
        for name, record in current.archived_storages.items()
        if record.archive.is_file()
    }
    if archived_storages == current.archived_storages:
        return current
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated
