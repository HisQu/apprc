"""Private directory creation and Windows access-control helpers."""

from __future__ import annotations

import os
from pathlib import Path


def create_private_directory_if_missing(path: Path) -> None:
    """Create a private directory without changing an existing directory.

    :param path: Directory needed by AppRC-managed private files or locks.
    """
    try:
        path.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        if path.is_dir():
            return
        raise
    if os.name == "nt":
        set_windows_private_acl(path)


def windows_acl_is_private(path: Path) -> bool:
    """Accept only current-user, SYSTEM, and Administrators allow entries.

    :param path: Existing file or directory to inspect.
    :return: Whether its Windows DACL grants access only to trusted accounts.
    """
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


def set_windows_private_acl(path: Path) -> None:
    """Restrict a newly created path to the current user and system accounts.

    :param path: Existing file or directory whose DACL should be replaced.
    """
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
