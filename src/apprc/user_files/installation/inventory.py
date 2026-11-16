"""Filesystem identities for exact installation cleanup inventories."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from apprc.definition.installation import InstallationError, InventoryEntry
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.writes import file_revision


def _link_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Select link metadata that does not change when its target is read."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def symlink_revision(path: Path) -> str | None:
    """Digest an exact symbolic link without reading or resolving its target.

    The digest covers the raw link target and stable ``lstat`` identity. Link
    targets remain private data rather than appearing in saved inventories.
    Ancestor links and non-symbolic reparse points retain the normal path guard.

    :param path: Absolute symbolic-link entry inside a separately validated root.
    :return: SHA-256 identity, or ``None`` if the entry is absent.
    :raises InstallationError: If the entry is not a stable symbolic link.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise InstallationError(
            "Symbolic-link inventory paths must be absolute and normalized."
        )
    assert_no_links(path.parent)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISLNK(before.st_mode):
        raise InstallationError(
            f"Expected an inventoried symbolic link: {path}."
        )
    try:
        target = os.readlink(path)
        after = path.lstat()
    except OSError as error:
        raise InstallationError(
            f"Symbolic link changed while inspecting: {path}."
        ) from error
    if _link_identity(before) != _link_identity(after):
        raise InstallationError(
            f"Symbolic link changed while inspecting: {path}."
        )
    assert_no_links(path.parent)
    content = json.dumps(
        (target, _link_identity(before)),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(content).hexdigest()


def cleanup_entry_revision(entry: InventoryEntry) -> str | None:
    """Read an entry's identity while retaining the appropriate link guard.

    :param entry: An exact typed inventory entry, not a recursive root claim.
    :return: File or symbolic-link revision; directories have no content revision.
    """
    if entry.kind in {"tree", "repository"}:
        return tree_revision(entry.path)
    if entry.kind == "symlink":
        return symlink_revision(entry.path)
    assert_no_links(entry.path)
    return file_revision(entry.path) if entry.kind == "file" else None


def tree_revision(path: Path) -> str | None:
    """Bind whole-directory consent to its filesystem identity, not its contents.

    :param path: Previously validated owned directory.
    :return: Stable identity digest, or None for an absent directory.
    """
    assert_no_links(path)
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstallationError(f"Cleanup root is not a directory: {path}.")
    return hashlib.sha256(
        f"{metadata.st_dev}:{metadata.st_ino}".encode()
    ).hexdigest()


def editable_repository(project: Path) -> Path:
    """Locate the nearest Git checkout containing an editable project.

    :param project: Registered project directory, possibly a workspace member.
    :return: Validated Git checkout root.
    """
    for candidate in (project, *project.parents):
        assert_no_links(candidate)
        marker = candidate / ".git"
        if marker.is_dir() or marker.is_file():
            if candidate in {Path(candidate.anchor), Path.home()}:
                raise InstallationError(
                    "Refusing repository deletion at a filesystem or home root."
                )
            return candidate
    raise InstallationError(
        "The editable project has no identifiable Git checkout."
    )
