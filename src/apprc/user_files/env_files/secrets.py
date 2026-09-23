"""Private companion files for AppRC-managed dotenv layers."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


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
        return SecretFileStatus(path, False, "The parent directory is missing.")
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
    parent_existed = path.parent.exists()
    if not parent_existed:
        path.parent.mkdir(parents=True, mode=0o700)
        if os.name == "nt":
            _set_windows_private_acl(path.parent)
    status = inspect_secret_file(path)
    if not status.available or path.exists():
        return status
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    if os.name == "nt":
        _set_windows_private_acl(path)
    return inspect_secret_file(path)


def repair_secret_file_permissions(path: Path) -> SecretFileStatus:
    """Make an explicitly approved parent and companion private.

    :param path: Existing or new secret companion.
    :return: Privacy state after repair.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        _set_windows_private_acl(path.parent)
    else:
        path.parent.chmod(0o700)
    if not path.exists():
        return ensure_secret_file(path)
    if path.is_symlink() or not path.is_file():
        return SecretFileStatus(path, False, "The secret path is not a file.")
    if os.name == "nt":
        _set_windows_private_acl(path)
    else:
        path.chmod(0o600)
    return inspect_secret_file(path)


def _private_path(path: Path) -> bool:
    """Reject a managed secret location accessible to ordinary other users."""
    if os.name == "nt":
        return _windows_acl_is_private(path)
    permissions = stat.S_IMODE(path.stat().st_mode)
    return permissions & 0o077 == 0


def _windows_acl_is_private(path: Path) -> bool:
    """Accept only current-user, SYSTEM, and Administrators allow entries."""
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32security  # pyright: ignore[reportMissingModuleSource]

    descriptor = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        return False
    user, _, _ = win32security.LookupAccountName(None, win32api.GetUserName())
    trusted = (
        user,
        win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
        win32security.CreateWellKnownSid(
            win32security.WinBuiltinAdministratorsSid
        ),
    )
    user_allowed = False
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
            continue
        if ace[2] not in trusted:
            return False
        if ace[2] == user:
            user_allowed = True
    return user_allowed


def _set_windows_private_acl(path: Path) -> None:
    """Replace inherited access with current-user and system access."""
    import ntsecuritycon  # pyright: ignore[reportMissingModuleSource]
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32security  # pyright: ignore[reportMissingModuleSource]

    user, _, _ = win32security.LookupAccountName(None, win32api.GetUserName())
    acl = win32security.ACL()
    inheritance = (
        win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
        if path.is_dir()
        else 0
    )
    for sid in (
        user,
        win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
        win32security.CreateWellKnownSid(
            win32security.WinBuiltinAdministratorsSid
        ),
    ):
        acl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            inheritance,
            ntsecuritycon.FILE_ALL_ACCESS,
            sid,
        )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
