"""Private companion files for AppRC-managed dotenv layers."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
    set_windows_private_acl,
    windows_acl_is_private,
)


@dataclass(frozen=True, slots=True)
class SecretFileStatus:
    """Report whether a layer can hold saved secret fields.

    :param path: Companion path beside an ordinary managed dotenv file.
    :param available: Whether the parent and existing companion are private.
    :param issue: Reason an unavailable companion cannot be written.
    """

    path: Path
    available: bool
    issue: str | None = None


def secret_companion_path(dotenv_path: Path) -> Path:
    """Place a secret file beside its user or storage dotenv layer.

    :param dotenv_path: Existing managed layer path.
    :return: Path ending in ``.secret.env``.
    """
    return dotenv_path.with_name(
        f"{dotenv_path.stem}.secret{dotenv_path.suffix}"
    )


def inspect_secret_file(path: Path) -> SecretFileStatus:
    """Check privacy without creating files or changing permissions.

    :param path: Secret companion to inspect.
    :return: Availability and a value-free error when unsafe.
    """
    if not path.parent.is_dir():
        issue = (
            "The parent path exists but is not a directory."
            if path.parent.exists()
            else "The parent directory is missing."
        )
        return SecretFileStatus(path, False, issue)
    if not _private_path(path.parent):
        return SecretFileStatus(
            path, False, "The parent directory is readable by other users."
        )
    if path.is_symlink() or (
        path.exists() and (not path.is_file() or not _private_path(path))
    ):
        return SecretFileStatus(
            path, False, "The secret file is readable by other users."
        )
    return SecretFileStatus(path, True)


def ensure_secret_file(path: Path) -> SecretFileStatus:
    """Create an empty companion only when its directory is private.

    :param path: Secret companion to initialize.
    :return: Privacy state after the attempt.
    """
    if not path.parent.exists():
        create_private_directory_if_missing(path.parent)
    status = inspect_secret_file(path)
    if not status.available or path.exists():
        return status
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    if os.name == "nt":
        set_windows_private_acl(path)
    return inspect_secret_file(path)


def repair_secret_file_permissions(path: Path) -> SecretFileStatus:
    """Make an explicitly approved parent and companion private.

    :param path: Existing or new secret companion.
    :return: Privacy state after repair.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        set_windows_private_acl(path.parent)
    else:
        path.parent.chmod(0o700)
    if not path.exists():
        return ensure_secret_file(path)
    if path.is_symlink() or not path.is_file():
        return SecretFileStatus(path, False, "The secret path is not a file.")
    if os.name == "nt":
        set_windows_private_acl(path)
    else:
        path.chmod(0o600)
    return inspect_secret_file(path)


def _private_path(path: Path) -> bool:
    """Reject a managed secret location accessible to ordinary other users."""
    if os.name == "nt":
        return windows_acl_is_private(path)
    permissions = stat.S_IMODE(path.stat().st_mode)
    return permissions & 0o077 == 0
