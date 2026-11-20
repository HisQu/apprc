"""Private path permission checks, directory creation and Windows ACL helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pywintypes  # pyright: ignore[reportMissingModuleSource]
    from _win32typing import PySECURITY_DESCRIPTOR, PySID  # pyright: ignore[reportMissingModuleSource]


def _path_permissions_are_private(
    path: Path, *, metadata: os.stat_result | None = None
) -> bool:
    """Check file or directory permissions without changing the path.

    Callers remain responsible for link and ownership checks. Windows checks
    only the ACL; POSIX checks mode bits using supplied metadata when available.

    :param path: File or directory whose permissions must exclude other users.
    :param metadata: Optional existing POSIX stat result to avoid another stat.
    :return: Whether the mode or ACL grants access only to private principals.
    """
    if os.name == "nt":
        return windows_acl_is_private(path)
    info = metadata if metadata is not None else path.stat()
    return stat.S_IMODE(info.st_mode) & 0o077 == 0


def create_private_directory(path: Path, *, exist_ok: bool = False) -> None:
    """Create a private directory without changing an existing directory.

    :param path: Directory needed by AppRC-managed private files or locks.
    :param exist_ok: Allow an existing directory without changing permissions.
    """
    try:
        if os.name == "nt":
            _create_windows_private_directory(path)
        else:
            path.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        if not exist_ok or not path.is_dir():
            raise


def create_private_directory_if_missing(path: Path) -> None:
    """Create the directory only if it does not already exist."""
    create_private_directory(path, exist_ok=True)


def _windows_user_sid() -> PySID:
    """Return the current process token's user SID without a name lookup."""
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]
    import win32security  # pyright: ignore[reportMissingModuleSource]

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    try:
        user, _ = win32security.GetTokenInformation(
            token, win32security.TokenUser
        )
        return user
    finally:
        win32api.CloseHandle(token)


def _windows_private_descriptor(
    *, for_directory: bool
) -> PySECURITY_DESCRIPTOR:
    """Build the protected DACL shared by directory creation and ACL updates."""
    import win32security  # pyright: ignore[reportMissingModuleSource]

    user = win32security.ConvertSidToStringSid(_windows_user_sid())
    inheritance = "OICI" if for_directory else ""
    sddl = "D:P" + "".join(
        f"(A;{inheritance};FA;;;{sid})" for sid in (user, "SY", "BA")
    )
    return win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, win32security.SDDL_REVISION_1
    )


def _windows_path_error(
    path: Path, action: str, error: pywintypes.error
) -> OSError:
    """Convert a pywin32 error into a native filesystem error with context."""
    return OSError(
        0, f"Cannot {action} ({error.strerror})", str(path), error.winerror
    )


def _create_windows_private_directory(path: Path) -> None:
    """Apply the private ACL atomically when creating the requested directory."""
    import pywintypes  # pyright: ignore[reportMissingModuleSource]
    import win32file  # pyright: ignore[reportMissingModuleSource]

    try:
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = _windows_private_descriptor(
            for_directory=True
        )
        try:
            win32file.CreateDirectory(str(path), attributes)
        except pywintypes.error as error:
            if error.winerror != 3:  # ERROR_PATH_NOT_FOUND
                raise
            path.parent.mkdir(parents=True, exist_ok=True)
            win32file.CreateDirectory(str(path), attributes)
    except pywintypes.error as error:
        raise _windows_path_error(
            path, "create the private directory", error
        ) from error


def windows_acl_is_private(path: Path) -> bool:
    """Accept only current-user, SYSTEM, and Administrators allow entries.

    :param path: Existing file or directory to inspect.
    :return: Whether its Windows DACL grants access only to trusted accounts.
    """
    import pywintypes  # pyright: ignore[reportMissingModuleSource]
    import win32security  # pyright: ignore[reportMissingModuleSource]

    try:
        descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        user = _windows_user_sid()
    except pywintypes.error as error:
        raise _windows_path_error(
            path, "inspect Windows permissions", error
        ) from error
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        return False
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


def set_windows_private_acl(path: Path) -> None:
    """Restrict a newly created path to the current user and system accounts.

    :param path: Existing file or directory whose DACL should be replaced.
    """
    import pywintypes  # pyright: ignore[reportMissingModuleSource]
    import win32security  # pyright: ignore[reportMissingModuleSource]

    try:
        descriptor = _windows_private_descriptor(for_directory=path.is_dir())
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            descriptor.GetSecurityDescriptorDacl(),
            None,
        )
    except pywintypes.error as error:
        raise _windows_path_error(
            path, "apply Windows permissions", error
        ) from error
