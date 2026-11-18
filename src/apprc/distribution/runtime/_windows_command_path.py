"""Select and expose Windows commands in the current user's shared bin."""

from __future__ import annotations

import ctypes
import ntpath
import os
from collections.abc import Mapping
from pathlib import Path

from apprc.definition.installation import InstallationError
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import managed_write_lock


def enabled() -> bool:
    """Whether the managed installer defaults to publishing a global command."""
    return os.name == "nt"


def _path_key(entry: str) -> str:
    return ntpath.normcase(ntpath.normpath(entry.strip().strip('"')))


def _contains_path(value: str, directory: Path) -> bool:
    expected = _path_key(str(directory))
    return any(
        _path_key(entry) == expected
        for entry in value.split(";")
        if entry.strip()
    )


def _read_path(root: int, key_name: str) -> tuple[str, int]:
    import winreg

    try:
        with winreg.OpenKey(root, key_name) as key:
            value, kind = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return "", winreg.REG_EXPAND_SZ
    if not isinstance(value, str) or kind not in {
        winreg.REG_SZ,
        winreg.REG_EXPAND_SZ,
    }:
        raise InstallationError("Windows PATH is not a string registry value.")
    return value, kind


def _registered_contains(value: str, kind: int, directory: Path) -> bool:
    import winreg

    if kind == winreg.REG_EXPAND_SZ:
        value = winreg.ExpandEnvironmentStrings(value)
    return _contains_path(value, directory)


def _machine_contains(directory: Path) -> bool:
    import winreg

    try:
        return _registered_contains(
            *_read_path(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
            directory,
        )
    except OSError:
        return False


def is_on_current_path(directory: Path, environment: Mapping[str, str]) -> bool:
    """Check the actual parent environment for command discovery."""
    return _contains_path(environment.get("PATH", ""), directory)


def is_on_path(directory: Path, environment: Mapping[str, str]) -> bool:
    """Check inherited and persisted PATH when choosing an existing bin."""
    import winreg

    if is_on_current_path(directory, environment):
        return True
    try:
        return _registered_contains(
            *_read_path(winreg.HKEY_CURRENT_USER, "Environment"), directory
        ) or _machine_contains(directory)
    except (OSError, ValueError):
        # > Read again under the write lock after installation has committed.
        return False


def _user_roots(environment: Mapping[str, str]) -> tuple[Path, ...]:
    home = (
        Path(environment["USERPROFILE"])
        if environment.get("USERPROFILE")
        else Path.home()
    )
    local = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
    return tuple(root.resolve() for root in (home, local) if root.is_absolute())


def is_user_directory(directory: Path, environment: Mapping[str, str]) -> bool:
    """Keep automatic publication within the current user's locations."""
    if not directory.is_absolute():
        return False
    resolved = directory.resolve(strict=False)
    return any(
        resolved != root and resolved.is_relative_to(root)
        for root in _user_roots(environment)
    )


def prepare_shared_bin(
    directory: Path,
    environment: Mapping[str, str],
    *,
    forbidden: tuple[Path, ...],
) -> None:
    """Create the shared user bin if needed without changing existing ACLs."""
    assert_no_links(directory)
    if not is_user_directory(directory, environment):
        raise InstallationError(
            f"Default command directory is outside the user profile: {directory}. Use --command-directory."
        )
    resolved = directory.resolve(strict=False)
    if any(
        resolved.is_relative_to(root.resolve(strict=False))
        for root in forbidden
    ):
        raise InstallationError(
            f"Default command directory is inside this installation or its runtime: {directory}."
        )
    if ";" in str(resolved):
        raise InstallationError(
            f"Default command directory cannot be represented in Windows PATH: {directory}."
        )
    create_private_directory_if_missing(directory)
    assert_no_links(directory)


def ensure_user_path(directory: Path, environment: Mapping[str, str]) -> bool:
    """Append one entry to the current user's PATH after a committed install."""
    import winreg

    local = Path(
        environment.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    )
    if not local.is_absolute():
        raise InstallationError(
            "Local AppData must be absolute to update user PATH."
        )
    # > The shared lock is outside all application installation and removal trees.
    with managed_write_lock(local / "AppRC" / "user-path"):
        value, kind = _read_path(winreg.HKEY_CURRENT_USER, "Environment")
        if _registered_contains(value, kind, directory) or _machine_contains(
            directory
        ):
            return False
        separator = ";" if value and not value.endswith(";") else ""
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(
                key, "Path", 0, kind, value + separator + str(directory)
            )
    return True


def notify_path_change() -> None:
    """Tell Windows shells that the user environment has changed."""
    from ctypes import wintypes

    send = ctypes.WinDLL("user32", use_last_error=True).SendMessageTimeoutW
    send.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPCWSTR,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    send.restype = ctypes.c_ssize_t
    if not send(
        0xFFFF,
        0x001A,
        0,
        "Environment",
        2,
        1000,
        ctypes.byref(ctypes.c_size_t()),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "Unable to notify Windows shells of the PATH update",
        )
