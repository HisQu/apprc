"""Transactional moves for registered storage directories."""

from __future__ import annotations

# == Standard Library ===========================================
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty
from apprc.user_files.storage_roots.paths import resolve_storage_root_path
from apprc.user_files.storage_roots.registry import repoint_storage


class StorageMoveError(ValueError):
    """A registered storage could not be moved safely."""


@dataclass(frozen=True, slots=True)
class StorageMoveResult:
    """Completed storage move.

    :param name: Registry selector that was moved.
    :param source: Previous storage root.
    :param destination: New registered root.
    :param warnings: Cleanup failures that did not invalidate the new root.
    """

    name: str
    source: Path
    destination: Path
    warnings: tuple[str, ...] = ()


def move_storage(
    *,
    name: str,
    destination: Path,
    path: Path,
) -> StorageMoveResult:
    """Move a complete registered directory and then update its root.

    The destination must be new or empty. Same-filesystem moves use a rename.
    Cross-filesystem moves copy to a private staging directory, verify that the
    source did not change, publish the copy, update the registry, and only then
    delete the original.

    :param name: Registered storage selector.
    :param destination: New root, relative to ``apprc.toml`` when not absolute.
    :param path: AppRC TOML path.
    :return: Completed move details.
    :raises StorageMoveError: If any safety precondition or committed step fails.
    """
    registry = load_storage_registry_or_empty(path)
    record = registry.selected(name)
    source = record.root
    if source.is_symlink():
        raise StorageMoveError(
            "Storage roots declared as symbolic links cannot be moved. "
            "Repoint the storage to its real directory first."
        )
    if not source.is_dir():
        raise StorageMoveError(f"Storage source is not a directory: {source}")
    source = source.resolve()
    shared_names = sorted(
        other_name
        for other_name, other_record in registry.storages.items()
        if other_name != name and other_record.root.resolve() == source
    )
    if shared_names:
        raise StorageMoveError(
            "Storage source is also registered by "
            f"{', '.join(repr(item) for item in shared_names)}. Repoint or "
            "remove those records first."
        )

    target = resolve_storage_root_path(destination, base=registry.path.parent)
    _validate_destination(source=source, destination=target)
    destination_existed = target.is_dir()
    backup = _park_empty_destination(target) if destination_existed else None

    try:
        same_filesystem = source.stat().st_dev == target.parent.stat().st_dev
        if same_filesystem:
            return _move_by_rename(
                name=name,
                source=source,
                destination=target,
                registry_path=registry.path,
                backup=backup,
            )
        return _move_by_copy(
            name=name,
            source=source,
            destination=target,
            registry_path=registry.path,
            backup=backup,
        )
    except Exception:
        _restore_empty_destination(target, backup)
        raise


def _validate_destination(*, source: Path, destination: Path) -> None:
    """Reject destinations that could merge or overwrite data.

    :param source: Existing storage directory.
    :param destination: Proposed destination.
    :raises StorageMoveError: If the destination is unsafe.
    """
    if destination == source:
        raise StorageMoveError(
            "Storage destination must differ from its source."
        )
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise StorageMoveError(
            "Storage source and destination must not contain each other."
        )
    if destination.is_symlink():
        raise StorageMoveError(
            f"Storage destination must not be a symbolic link: {destination}"
        )
    if destination.exists():
        if not destination.is_dir():
            raise StorageMoveError(
                f"Storage destination is not a directory: {destination}"
            )
        if any(destination.iterdir()):
            raise StorageMoveError(
                f"Storage destination must be new or empty: {destination}"
            )
    elif not destination.parent.is_dir():
        raise StorageMoveError(
            "Storage destination parent does not exist or is not a directory: "
            f"{destination.parent}"
        )


def _park_empty_destination(destination: Path) -> Path:
    """Rename an empty destination until the storage move commits.

    :param destination: Existing empty directory.
    :return: Private sibling backup path.
    """
    backup = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.apprc-empty-",
            dir=destination.parent,
        )
    )
    backup.rmdir()
    os.replace(destination, backup)
    return backup


def _move_by_rename(
    *,
    name: str,
    source: Path,
    destination: Path,
    registry_path: Path,
    backup: Path | None,
) -> StorageMoveResult:
    """Commit a same-filesystem directory rename.

    :param name: Registered selector.
    :param source: Existing root.
    :param destination: New root.
    :param registry_path: AppRC TOML path.
    :param backup: Parked original empty destination.
    :return: Completed move details.
    """
    try:
        os.replace(source, destination)
        repoint_storage(name=name, root=destination, path=registry_path)
    except Exception as exc:
        if destination.exists() and not source.exists():
            try:
                os.replace(destination, source)
            except OSError as rollback_exc:
                raise StorageMoveError(
                    f"{exc}; rollback also failed: {rollback_exc}"
                ) from exc
        raise StorageMoveError(str(exc)) from exc
    warning = _discard_empty_backup(backup)
    return StorageMoveResult(
        name=name,
        source=source,
        destination=destination,
        warnings=(warning,) if warning is not None else (),
    )


def _move_by_copy(
    *,
    name: str,
    source: Path,
    destination: Path,
    registry_path: Path,
    backup: Path | None,
) -> StorageMoveResult:
    """Commit a verified cross-filesystem copy.

    :param name: Registered selector.
    :param source: Existing root.
    :param destination: New root.
    :param registry_path: AppRC TOML path.
    :param backup: Parked original empty destination.
    :return: Completed move details.
    """
    snapshot = _directory_snapshot(source)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.apprc-moving-",
            dir=destination.parent,
        )
    )
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True, symlinks=True)
        if _directory_snapshot(source) != snapshot:
            raise StorageMoveError(
                "Storage source changed while it was copied; no registry "
                "change was made."
            )
        os.replace(staging, destination)
        repoint_storage(name=name, root=destination, path=registry_path)
    except Exception as exc:
        candidate = destination if destination.exists() else staging
        if candidate.exists() and candidate.is_dir():
            shutil.rmtree(candidate)
        if isinstance(exc, StorageMoveError):
            raise
        raise StorageMoveError(str(exc)) from exc

    warnings: list[str] = []
    try:
        if _directory_snapshot(source) == snapshot:
            shutil.rmtree(source)
        else:
            warnings.append(
                f"Source changed after registry update and was kept: {source}"
            )
    except OSError as exc:
        warnings.append(
            f"Could not remove previous storage root {source}: {exc}"
        )
    backup_warning = _discard_empty_backup(backup)
    if backup_warning is not None:
        warnings.append(backup_warning)
    return StorageMoveResult(
        name=name,
        source=source,
        destination=destination,
        warnings=tuple(warnings),
    )


def _directory_snapshot(
    root: Path,
) -> tuple[tuple[str, int, int, int, int], ...]:
    """Return metadata that detects tree changes during a copy.

    :param root: Directory to inspect without following symlinks.
    :return: Sorted relative paths and ``lstat`` metadata.
    """
    entries: list[tuple[str, int, int, int, int]] = []
    for parent, directory_names, file_names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for child_name in (".", *directory_names, *file_names):
            entry = (
                parent_path if child_name == "." else parent_path / child_name
            )
            stat = entry.lstat()
            relative = "." if entry == root else str(entry.relative_to(root))
            entries.append(
                (
                    relative,
                    stat.st_mode,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
            )
    return tuple(sorted(set(entries)))


def _restore_empty_destination(
    destination: Path,
    backup: Path | None,
) -> None:
    """Restore a parked empty destination after a failed move.

    :param destination: Intended storage destination.
    :param backup: Parked empty directory, if one existed.
    """
    if backup is None or not backup.exists() or destination.exists():
        return
    os.replace(backup, destination)


def _discard_empty_backup(backup: Path | None) -> str | None:
    """Remove a parked empty directory after commit.

    :param backup: Parked empty directory, if one existed.
    :return: Cleanup warning, if removal failed.
    """
    if backup is None or not backup.exists():
        return None
    try:
        backup.rmdir()
    except OSError as exc:
        return f"Could not remove empty destination backup {backup}: {exc}"
    return None
