"""Archive and restore AppRC storage directories.

Storage registries only point at live directories. This module provides the
separate convenience layer used by the Textual editor to compress a storage
into ``*.apprc.tar.xz`` and later restore that archive into a directory.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ARCHIVE_SUFFIX = ".apprc.tar.xz"
ProgressCallback = Callable[["StorageArchiveProgress"], None]


@dataclass(frozen=True, slots=True)
class StorageArchiveProgress:
    """Progress emitted during storage archive operations.

    :param completed: Number of members already processed.
    :param total: Total member count planned for the operation.
    :param path: Current source or archive member path.
    """

    completed: int
    total: int
    path: Path | str


def is_storage_archive_path(path: str | Path) -> bool:
    """Return whether ``path`` uses AppRC's storage archive suffix."""
    return Path(path).name.endswith(ARCHIVE_SUFFIX)


def storage_archive_default_path(storage_root: Path) -> Path:
    """Return the default archive path for one live storage root."""
    root = Path(storage_root).expanduser()
    return root.with_name(f"{root.name}{ARCHIVE_SUFFIX}")


def storage_root_name_from_archive(archive_path: Path) -> str:
    """Return a suggested directory/storage name from an archive filename."""
    name = Path(archive_path).name
    if name.endswith(ARCHIVE_SUFFIX):
        return name[: -len(ARCHIVE_SUFFIX)]
    return Path(archive_path).stem


def archive_directory(
    *,
    source_root: Path,
    archive_path: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    """Compress a live storage directory into ``*.apprc.tar.xz``.

    The archive stores storage contents relative to ``source_root`` so callers
    can restore them into any destination directory. The destination file is
    replaced atomically after a complete tar stream has been written.

    :param source_root: Existing directory to compress.
    :param archive_path: Archive file to create or replace.
    :param progress: Optional callback for progress bar updates.
    :return: Written archive path.
    :raises ValueError: If the source or archive path is invalid.
    """
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Storage root does not exist: {root}")

    archive = Path(archive_path).expanduser()
    if not is_storage_archive_path(archive):
        raise ValueError(f"Storage archives must end with {ARCHIVE_SUFFIX}.")
    archive.parent.mkdir(parents=True, exist_ok=True)
    final_archive = archive.resolve()
    temp_archive = final_archive.with_name(f".{final_archive.name}.tmp")
    if temp_archive.exists():
        temp_archive.unlink()

    members = _storage_members(root)
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


def extract_archive(
    *,
    archive_path: Path,
    destination_root: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    """Restore a storage archive into a destination directory.

    :param archive_path: Existing ``*.apprc.tar.xz`` file.
    :param destination_root: Directory that should receive archive contents.
    :param progress: Optional callback for progress bar updates.
    :return: Destination directory.
    :raises ValueError: If the archive path, destination, or member names are
        unsafe.
    """
    archive = Path(archive_path).expanduser().resolve()
    if not is_storage_archive_path(archive):
        raise ValueError(f"Storage archives must end with {ARCHIVE_SUFFIX}.")
    if not archive.is_file():
        raise ValueError(f"Storage archive does not exist: {archive}")

    destination = Path(destination_root).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:xz") as tar:
        members = tar.getmembers()
        total = len(members)
        for index, member in enumerate(members, start=1):
            _validate_member(destination, member)
            tar.extract(
                member,
                path=destination,
                set_attrs=True,
                filter="data",
            )
            _report_progress(
                progress,
                completed=index,
                total=total,
                path=member.name,
            )
    return destination


def _storage_members(root: Path) -> list[Path]:
    """Return archive members in deterministic relative path order."""
    return sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _validate_member(destination: Path, member: tarfile.TarInfo) -> None:
    """Reject archive members that could escape ``destination``."""
    if member.issym() or member.islnk():
        raise ValueError(
            f"Storage archives may not contain links: {member.name}"
        )
    target = (destination / member.name).resolve()
    if target != destination and not target.is_relative_to(destination):
        raise ValueError(
            f"Storage archive member escapes destination: {member.name}"
        )


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
        StorageArchiveProgress(
            completed=completed,
            total=total,
            path=path,
        )
    )
