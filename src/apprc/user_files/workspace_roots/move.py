"""Transactional moves for registered workspace directories."""

from __future__ import annotations

# == Standard Library ===========================================
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.user_files.workspace_roots._io import (
    load_workspace_registry_or_empty,
)
from apprc.user_files.workspace_roots.paths import resolve_workspace_root_path
from apprc.user_files.workspace_roots.registry import repoint_workspace


class WorkspaceMoveError(ValueError):
    """A registered workspace could not be moved safely."""


@dataclass(frozen=True, slots=True)
class WorkspaceMoveResult:
    """Completed workspace move.

    :param name: Registry selector that was moved.
    :param source: Previous workspace root.
    :param destination: New registered root.
    :param warnings: Cleanup failures that did not invalidate the new root.
    """

    name: str
    source: Path
    destination: Path
    warnings: tuple[str, ...] = ()


def move_workspace(
    *,
    name: str,
    destination: Path,
    path: Path,
) -> WorkspaceMoveResult:
    """Move a registered workspace and update its root in the registry.

    Same-filesystem moves use a rename. Cross-filesystem moves copy to a private
    staging directory, verify the source is unchanged, publish the copy, update
    the registry, and then delete the original.

    :param name: Registered workspace selector.
    :param destination: New root, relative to ``apprc.toml`` when not absolute.
    :param path: AppRC TOML path.
    :return: Completed move details.
    :raises WorkspaceMoveError: If a safety precondition or committed step fails.
    """
    registry = load_workspace_registry_or_empty(path)
    record = registry.selected(name)
    source = record.root
    if source.is_symlink():
        raise WorkspaceMoveError(
            "Workspace roots declared as symbolic links cannot be moved. "
            "Repoint the workspace to its real directory first."
        )
    if not source.is_dir():
        raise WorkspaceMoveError(
            f"Workspace source is not a directory: {source}"
        )
    source = source.resolve()
    shared_names = sorted(
        other_name
        for other_name, other_record in registry.workspaces.items()
        if other_name != name and other_record.root.resolve() == source
    )
    if shared_names:
        raise WorkspaceMoveError(
            "Workspace source is also registered by "
            f"{', '.join(repr(item) for item in shared_names)}. Repoint or "
            "remove those records first."
        )

    target = resolve_workspace_root_path(destination, base=registry.path.parent)
    target_identity = _validate_destination(source=source, destination=target)
    backup = (
        _park_empty_destination(target, target_identity)
        if target_identity is not None
        else None
    )

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


def _validate_destination(
    *, source: Path, destination: Path
) -> os.stat_result | None:
    """Reject destinations that could merge or overwrite workspace data.

    :param source: Existing workspace directory.
    :param destination: Proposed destination.
    :return: Identity of an existing empty destination, if present.
    :raises WorkspaceMoveError: If the destination is unsafe.
    """
    if destination == source:
        raise WorkspaceMoveError(
            "Workspace destination must differ from its source."
        )
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise WorkspaceMoveError(
            "Workspace source and destination must not contain each other."
        )
    try:
        identity = destination.lstat()
    except FileNotFoundError:
        if not destination.parent.is_dir():
            raise WorkspaceMoveError(
                "Workspace destination parent does not exist or is not a directory: "
                f"{destination.parent}"
            ) from None
        return None
    if stat.S_ISLNK(identity.st_mode):
        raise WorkspaceMoveError(
            f"Workspace destination must not be a symbolic link: {destination}"
        )
    if not stat.S_ISDIR(identity.st_mode):
        raise WorkspaceMoveError(
            f"Workspace destination is not a directory: {destination}"
        )
    if any(destination.iterdir()):
        raise WorkspaceMoveError(
            f"Workspace destination must be new or empty: {destination}"
        )
    return identity


def _park_empty_destination(
    destination: Path, identity: os.stat_result
) -> tuple[Path, os.stat_result]:
    """Rename an empty destination until the workspace move commits.

    :param destination: Existing empty directory.
    :param identity: Identity captured when validating the destination.
    :return: Private sibling backup path and original directory identity.
    """
    backup = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.apprc-empty-",
            dir=destination.parent,
        )
    )
    backup.rmdir()
    if not _owns_directory(destination, identity) or any(destination.iterdir()):
        raise WorkspaceMoveError(
            f"Workspace destination changed: {destination}"
        )
    _require_absent(backup)
    os.replace(destination, backup)
    return backup, identity


def _owns_directory(path: Path, expected: os.stat_result) -> bool:
    """Check a directory entry's identity without following a replacement link.

    :param path: Entry that the operation expects to own.
    :param expected: Metadata captured before publishing or parking it.
    :return: Whether the entry is still the expected directory.
    """
    try:
        actual = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(actual.st_mode) and os.path.samestat(actual, expected)


def _require_absent(path: Path) -> None:
    """Raise if another writer has occupied a destination.

    :param path: Path expected to be vacant before a move or restoration.
    """
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise WorkspaceMoveError(f"Workspace directory is occupied: {path}")


def _move_by_rename(
    *,
    name: str,
    source: Path,
    destination: Path,
    registry_path: Path,
    backup: tuple[Path, os.stat_result] | None,
) -> WorkspaceMoveResult:
    """Commit a same-filesystem directory rename.

    :param name: Registered selector.
    :param source: Existing root.
    :param destination: New root.
    :param registry_path: AppRC TOML path.
    :param backup: Parked original empty destination.
    :return: Completed move details.
    """
    identity = source.lstat()
    published = False
    try:
        _require_absent(destination)
        os.replace(source, destination)
        published = True
        if not _owns_directory(destination, identity):
            raise WorkspaceMoveError(
                f"Workspace destination changed: {destination}"
            )
        repoint_workspace(name=name, root=destination, path=registry_path)
    except Exception as exc:
        if published:
            try:
                if not _owns_directory(destination, identity):
                    raise WorkspaceMoveError(
                        f"Published workspace directory changed: {destination}"
                    )
                _require_absent(source)
                os.replace(destination, source)
            except (OSError, WorkspaceMoveError) as rollback_exc:
                raise WorkspaceMoveError(
                    f"{exc}; rollback also failed: {rollback_exc}"
                ) from exc
        raise WorkspaceMoveError(str(exc)) from exc
    warning = _discard_empty_backup(backup)
    return WorkspaceMoveResult(
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
    backup: tuple[Path, os.stat_result] | None,
) -> WorkspaceMoveResult:
    """Commit a verified cross-filesystem copy.

    :param name: Registered selector.
    :param source: Existing root.
    :param destination: New root.
    :param registry_path: AppRC TOML path.
    :param backup: Parked original empty destination.
    :return: Completed move details.
    """
    source_identity = source.lstat()
    snapshot = _directory_snapshot(source)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.apprc-moving-",
            dir=destination.parent,
        )
    )
    identity = staging.lstat()
    published = False
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True, symlinks=True)
        if _directory_snapshot(source) != snapshot:
            raise WorkspaceMoveError(
                "Workspace source changed while it was copied; no registry "
                "change was made."
            )
        _require_absent(destination)
        os.replace(staging, destination)
        published = True
        if not _owns_directory(destination, identity):
            raise WorkspaceMoveError(
                f"Workspace destination changed: {destination}"
            )
        repoint_workspace(name=name, root=destination, path=registry_path)
    except Exception as exc:
        candidate = destination if published else staging
        try:
            if _owns_directory(candidate, identity):
                shutil.rmtree(candidate)
        except OSError as rollback_exc:
            raise WorkspaceMoveError(
                f"{exc}; rollback also failed: {rollback_exc}"
            ) from exc
        if isinstance(exc, WorkspaceMoveError):
            raise
        raise WorkspaceMoveError(str(exc)) from exc

    warnings: list[str] = []
    try:
        if not _owns_directory(destination, identity):
            warnings.append(
                f"Destination changed after registry update. Previous workspace root kept: {source}"
            )
        elif (
            _owns_directory(source, source_identity)
            and _directory_snapshot(source) == snapshot
        ):
            shutil.rmtree(source)
        else:
            warnings.append(
                f"Source changed after registry update and was kept: {source}"
            )
    except OSError as exc:
        warnings.append(
            f"Could not remove previous workspace root {source}: {exc}"
        )
    backup_warning = _discard_empty_backup(backup)
    if backup_warning is not None:
        warnings.append(backup_warning)
    return WorkspaceMoveResult(
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
    backup: tuple[Path, os.stat_result] | None,
) -> None:
    """Restore a parked empty destination after a failed move.

    :param destination: Intended workspace destination.
    :param backup: Parked empty directory, if one existed.
    """
    if backup is None:
        return
    path, identity = backup
    if not _owns_directory(path, identity):
        return
    try:
        _require_absent(destination)
    except WorkspaceMoveError:
        return
    os.replace(path, destination)


def _discard_empty_backup(
    backup: tuple[Path, os.stat_result] | None,
) -> str | None:
    """Remove a parked empty directory after commit.

    :param backup: Parked empty directory, if one existed.
    :return: Cleanup warning, if removal failed.
    """
    if backup is None:
        return None
    path, identity = backup
    try:
        if not _owns_directory(path, identity):
            if os.path.lexists(path):
                return f"Empty destination backup changed and was kept: {path}"
            return None
        path.rmdir()
    except OSError as exc:
        return f"Could not remove empty destination backup {path}: {exc}"
    return None
