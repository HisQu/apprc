"""Archive and restore AppRC workspace directories.

Workspace registries point at live directories. This module compresses a
workspace into ``*.apprc.tar.xz`` and restores archives into destination roots.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ARCHIVE_SUFFIX = ".apprc.tar.xz"
ProgressCallback = Callable[["WorkspaceArchiveProgress"], None]


@dataclass(frozen=True, slots=True)
class WorkspaceArchiveProgress:
    """Progress emitted during workspace archive operations.

    :param completed: Number of members already processed.
    :param total: Total member count planned for the operation.
    :param path: Current source or archive member path.
    """

    completed: int
    total: int
    path: Path | str


def is_workspace_archive_path(path: str | Path) -> bool:
    """Return whether ``path`` uses AppRC's workspace archive suffix."""
    return Path(path).name.endswith(ARCHIVE_SUFFIX)


def workspace_archive_default_path(workspace_root: Path) -> Path:
    """Return the default archive path for one live workspace root."""
    root = Path(workspace_root).expanduser()
    return root.with_name(f"{root.name}{ARCHIVE_SUFFIX}")


def workspace_root_name_from_archive(archive_path: Path) -> str:
    """Return a suggested directory/workspace name from an archive filename."""
    name = Path(archive_path).name
    if name.endswith(ARCHIVE_SUFFIX):
        return name[: -len(ARCHIVE_SUFFIX)]
    return Path(archive_path).stem


def archive_workspace_directory(
    *,
    source_root: Path,
    archive_path: Path,
    progress: ProgressCallback | None = None,
    excluded_names: tuple[str, ...] = ("apprc.workspace.secret.env",),
) -> Path:
    """Compress a live workspace directory into ``*.apprc.tar.xz``.

    The archive stores workspace contents relative to ``source_root`` so
    callers can restore them into any destination directory. The destination
    file is replaced atomically after a complete tar stream has been written.

    :param source_root: Existing workspace directory to compress.
    :param archive_path: Archive file to create or replace.
    :param progress: Optional callback for progress bar updates.
    :return: Written archive path.
    :raises ValueError: If the source or archive path is invalid.
    """
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace root does not exist: {root}")

    archive = Path(archive_path).expanduser()
    if not is_workspace_archive_path(archive):
        raise ValueError(f"Workspace archives must end with {ARCHIVE_SUFFIX}.")
    final_archive = archive.resolve()
    temp_archive = final_archive.with_name(f".{final_archive.name}.tmp")
    if temp_archive.exists():
        temp_archive.unlink()

    members = [
        member
        for member in _validated_workspace_members(root)
        if not (member.parent == root and member.name in excluded_names)
    ]
    archive.parent.mkdir(parents=True, exist_ok=True)
    total = len(members)
    try:
        with tarfile.open(temp_archive, "w:xz", preset=9) as tar:
            for index, member in enumerate(members, start=1):
                relative = member.relative_to(root)
                tar.add(member, arcname=relative.as_posix(), recursive=False)
                _report_progress(
                    progress,
                    completed=index,
                    total=total,
                    path=member,
                )
        os.replace(temp_archive, final_archive)
    finally:
        if temp_archive.exists():
            temp_archive.unlink()
    return final_archive


def extract_workspace_archive(
    *,
    archive_path: Path,
    destination_root: Path,
    progress: ProgressCallback | None = None,
    replace_existing: bool = False,
    after_install: Callable[[Path], None] | None = None,
) -> Path:
    """Restore a workspace archive into a destination directory.

    :param archive_path: Existing ``*.apprc.tar.xz`` file.
    :param destination_root: Directory that should receive archive contents.
    :param progress: Optional callback for progress bar updates.
    :param replace_existing: Whether a non-empty destination may be replaced.
    :param after_install: Optional commit callback run while filesystem rollback
        remains possible.
    :return: Destination directory.
    :raises ValueError: If the archive path, destination, or member names are
        unsafe.
    """
    archive = Path(archive_path).expanduser().resolve()
    if not is_workspace_archive_path(archive):
        raise ValueError(f"Workspace archives must end with {ARCHIVE_SUFFIX}.")
    if not archive.is_file():
        raise ValueError(f"Workspace archive does not exist: {archive}")

    destination = Path(destination_root).expanduser().resolve()
    with tarfile.open(archive, "r:xz") as tar:
        members = tar.getmembers()
        _validate_archive_members(destination, members)
        _validate_destination(destination, replace_existing=replace_existing)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged_destination = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.apprc-extract-",
                dir=destination.parent,
            )
        )
        total = len(members)
        try:
            for index, member in enumerate(members, start=1):
                tar.extract(
                    member,
                    path=staged_destination,
                    set_attrs=True,
                    filter="data",
                )
                _report_progress(
                    progress,
                    completed=index,
                    total=total,
                    path=member.name,
                )
            _install_staged_extract(
                staged_destination=staged_destination,
                destination=destination,
                replace_existing=replace_existing,
                after_install=after_install,
            )
        finally:
            if staged_destination.exists():
                shutil.rmtree(staged_destination, ignore_errors=True)
    return destination


def _workspace_members(root: Path) -> list[Path]:
    """Return archive members in deterministic relative path order."""
    return sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _validated_workspace_members(root: Path) -> list[Path]:
    """Return source members after enforcing archive link policy."""
    members = _workspace_members(root)
    _validate_source_members(root, members)
    return members


def _validate_source_members(root: Path, members: list[Path]) -> None:
    """Reject source entries that would produce link archive members."""
    linked_files: dict[tuple[int, int], Path] = {}
    for member in members:
        relative = member.relative_to(root).as_posix()
        try:
            member_stat = member.lstat()
        except OSError as exc:
            raise ValueError(
                "Workspace archive member could not be inspected: "
                f"{relative}: {exc}"
            ) from exc
        if stat.S_ISLNK(member_stat.st_mode):
            raise ValueError(
                f"Workspace archives may not contain links: {relative}"
            )
        if not stat.S_ISREG(member_stat.st_mode) or member_stat.st_nlink <= 1:
            continue
        identity = (member_stat.st_dev, member_stat.st_ino)
        if identity in linked_files:
            raise ValueError(
                f"Workspace archives may not contain links: {relative}"
            )
        linked_files[identity] = member


def _validate_member(destination: Path, member: tarfile.TarInfo) -> None:
    """Reject archive members that could escape ``destination``."""
    if member.issym() or member.islnk():
        raise ValueError(
            f"Workspace archives may not contain links: {member.name}"
        )
    target = (destination / member.name).resolve()
    if target != destination and not target.is_relative_to(destination):
        raise ValueError(
            f"Workspace archive member escapes destination: {member.name}"
        )


def _validate_archive_members(
    destination: Path,
    members: list[tarfile.TarInfo],
) -> None:
    """Reject unsafe archive members before extraction starts."""
    names: set[str] = set()
    for member in members:
        if member.name in names:
            raise ValueError(
                f"Workspace archive contains duplicate member: {member.name}"
            )
        names.add(member.name)
        _validate_member(destination, member)


def _validate_destination(
    destination: Path,
    *,
    replace_existing: bool,
) -> None:
    """Reject destination states that cannot be restored safely."""
    if destination.is_symlink():
        raise ValueError(
            f"Workspace archive destination must not be a symlink: {destination}"
        )
    if not destination.exists():
        return
    if not destination.is_dir():
        raise ValueError(
            "Workspace archive destination exists but is not a directory: "
            f"{destination}"
        )
    if any(destination.iterdir()) and not replace_existing:
        raise ValueError(
            "Workspace archive destination is not empty: "
            f"{destination}. Pass replace_existing=True to replace it."
        )


def _install_staged_extract(
    *,
    staged_destination: Path,
    destination: Path,
    replace_existing: bool,
    after_install: Callable[[Path], None] | None,
) -> None:
    """Move a staged restore and keep rollback available through commit.

    :param staged_destination: Fully extracted temporary directory.
    :param destination: Final workspace root.
    :param replace_existing: Whether existing contents may be replaced.
    :param after_install: Optional registry commit callback.
    :return: None.
    """
    if not destination.exists():
        os.replace(staged_destination, destination)
        try:
            if after_install is not None:
                after_install(destination)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return
    if any(destination.iterdir()) and not replace_existing:
        raise ValueError(
            "Workspace archive destination is not empty: "
            f"{destination}. Pass replace_existing=True to replace it."
        )
    backup = _backup_path(destination)
    replaced_original = False
    committed = False
    try:
        os.replace(destination, backup)
        replaced_original = True
        os.replace(staged_destination, destination)
        if after_install is not None:
            after_install(destination)
        committed = True
    except Exception:
        if replaced_original and backup.exists():
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            os.replace(backup, destination)
        raise
    finally:
        if committed and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _backup_path(destination: Path) -> Path:
    """Return a non-existing sibling path for restore rollback."""
    backup_parent = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.apprc-backup-",
            dir=destination.parent,
        )
    )
    backup_parent.rmdir()
    return backup_parent


def _report_progress(
    progress: ProgressCallback | None,
    *,
    completed: int,
    total: int,
    path: Path | str,
) -> None:
    """Emit one progress callback when a receiver is configured."""
    if progress is None:
        return
    progress(
        WorkspaceArchiveProgress(
            completed=completed,
            total=total,
            path=path,
        )
    )
