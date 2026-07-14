"""Operations for optional AppRC multi-storage registries."""

from __future__ import annotations

# == Standard Library ========================
import logging
from dataclasses import replace
from pathlib import Path

# == Internal ================================
from apprc.user_files.storage_roots._io import (
    load_storage_registry_or_empty,
    ordered_storage_names,
    write_storage_registry,
)
from apprc.user_files.env_files.files import ensure_storage_env_file
from apprc.user_files.storage_roots.model import (
    ArchivedStorageRecord,
    StorageRecord,
    StorageRegistry,
)
from apprc.user_files.storage_roots._naming import (
    app_data_dir,
    suggested_storage_name,
    suggested_storage_root,
    validate_storage_name,
)
from apprc.user_files.storage_roots.paths import normalize_storage_root_path

LOG = logging.getLogger(__name__)

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
    :param storage_env_filename: Storage dotenv filename to create.
    :return: Updated registry.
    """
    validate_storage_name(name)
    resolved_root = normalize_storage_root_path(root).resolve()
    current = load_storage_registry_or_empty(path)
    root_existed = resolved_root.exists()
    storage_env = resolved_root / storage_env_filename
    storage_env_existed = storage_env.exists()

    try:
        resolved_root.mkdir(parents=True, exist_ok=True)
        ensure_storage_env_file(resolved_root, filename=storage_env_filename)
        updated = replace(
            current,
            storages={
                **dict(current.storages),
                name: StorageRecord(name=name, root=resolved_root),
            },
        )
        write_storage_registry(updated)
    except Exception as exc:
        _rollback_created_storage_artifacts(
            root=resolved_root,
            root_existed=root_existed,
            storage_env=storage_env,
            storage_env_existed=storage_env_existed,
            original_error=exc,
        )
        raise
    return updated


def _update_storage(
    *,
    current_name: str,
    name: str,
    root: Path | None,
    path: Path,
) -> StorageRegistry:
    """Rename or repoint one registered storage without touching its files.

    The editor uses this operation when changing registry metadata. It keeps
    the storage directory and dotenv file in place, and moves matching archive
    metadata to the new selector when the name changes. Passing ``None`` for
    ``root`` preserves the stored path spelling for a name-only update.

    :param current_name: Existing live storage selector to replace.
    :param name: New selector for the storage record.
    :param root: New storage root recorded in the registry, or ``None`` to
        preserve the current root exactly.
    :param path: AppRC TOML location.
    :return: Updated registry after one atomic write.
    :raises ValueError: If the source is missing or the target name is used by
        another live or archived storage.
    """
    validate_storage_name(current_name)
    current = load_storage_registry_or_empty(path)
    current_record = current.selected(current_name)
    validate_storage_name(name)
    updated_root = (
        current_record.root
        if root is None
        else normalize_storage_root_path(root).resolve()
    )

    if name != current_name:
        if name in current.storages:
            raise ValueError(
                f"Storage name {name!r} is already used by a live storage."
            )
        if name in current.archived_storages:
            raise ValueError(
                f"Storage name {name!r} is already used by an archived storage."
            )

    storages = dict(current.storages)
    storages.pop(current_name)
    storages[name] = StorageRecord(name=name, root=updated_root)

    archived_storages = dict(current.archived_storages)
    if name != current_name:
        archived_record = archived_storages.pop(current_name, None)
        if archived_record is not None:
            archived_storages[name] = replace(archived_record, name=name)

    updated = replace(
        current,
        storages=storages,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def _rollback_created_storage_artifacts(
    *,
    root: Path,
    root_existed: bool,
    storage_env: Path,
    storage_env_existed: bool,
    original_error: Exception,
) -> None:
    """Best-effort removal of empty artifacts from a failed registration.

    :param root: Storage root that may have been created by registration.
    :param root_existed: Whether the root existed before registration.
    :param storage_env: Storage dotenv path that may have been created.
    :param storage_env_existed: Whether the dotenv file existed beforehand.
    :param original_error: Registration error that receives cleanup notes.
    """
    if not storage_env_existed:
        try:
            if storage_env.is_file() and storage_env.stat().st_size == 0:
                storage_env.unlink()
        except OSError as exc:
            _record_rollback_cleanup_failure(
                original_error=original_error,
                action="remove empty storage env file",
                path=storage_env,
                cleanup_error=exc,
            )
    if root_existed:
        return
    try:
        root.rmdir()
    except OSError as exc:
        _record_rollback_cleanup_failure(
            original_error=original_error,
            action="remove created storage root",
            path=root,
            cleanup_error=exc,
        )


def _record_rollback_cleanup_failure(
    *,
    original_error: Exception,
    action: str,
    path: Path,
    cleanup_error: OSError,
) -> None:
    """Expose one rollback cleanup failure without masking the root cause.

    :param original_error: Registration error that remains the raised error.
    :param action: Human-readable cleanup action that failed.
    :param path: Filesystem path targeted by cleanup.
    :param cleanup_error: Cleanup failure raised by the filesystem.
    """
    message = (
        "Storage registration rollback could not "
        f"{action} {path}: {cleanup_error}"
    )
    LOG.warning(message)
    original_error.add_note(message)


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
