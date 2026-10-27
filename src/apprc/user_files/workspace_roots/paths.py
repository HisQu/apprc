"""Path normalization helpers for AppRC workspace roots."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# == Internal ================================
from apprc.user_files.app_home._paths import normalize_apprc_toml_path

__all__ = [
    "WorkspaceRootPathError",
    "normalize_apprc_toml_path",
    "normalize_workspace_root_path",
    "resolve_workspace_root_path",
    "windows_drive_path_to_posix",
]

_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_MALFORMED_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:(?![\\/])")
_IS_NATIVE_WINDOWS = sys.platform == "win32"


class WorkspaceRootPathError(ValueError):
    """Raised when workspace-root text cannot be safely interpreted."""


def normalize_workspace_root_path(path: str | Path) -> Path:
    """Return a platform-readable workspace root path.

    :param path: User-provided workspace root path.
    :return: Expanded local path without requiring the directory to exist.
    """
    path_text = str(path).strip()
    if not path_text:
        raise WorkspaceRootPathError("Workspace root path must not be empty.")
    if _is_malformed_windows_drive_path(path_text):
        raise WorkspaceRootPathError(
            _malformed_windows_drive_path_message(path_text)
        )
    if _is_windows_drive_path(path_text) and not _IS_NATIVE_WINDOWS:
        return windows_drive_path_to_posix(path_text).expanduser()
    return Path(path_text).expanduser()


def resolve_workspace_root_path(path: str | Path, *, base: Path) -> Path:
    """Resolve workspace-root text against the supplied base directory."""
    normalized = normalize_workspace_root_path(path)
    if normalized.is_absolute():
        return Path(os.path.abspath(normalized))
    return Path(
        os.path.abspath(Path(base).expanduser().absolute() / normalized)
    )


def windows_drive_path_to_posix(path: str) -> Path:
    """Translate ``C:\\...`` or ``C:/...`` text to a POSIX path.

    :param path: Windows drive path text.
    :return: WSL-style POSIX path.
    """
    if shutil.which("wslpath"):
        try:
            result = subprocess.run(
                ["wslpath", "-u", "-a", path],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return _windows_drive_fallback_path(path)
        else:
            converted = result.stdout.strip()
            if converted:
                return Path(converted)

    return _windows_drive_fallback_path(path)


def _windows_drive_fallback_path(path: str) -> Path:
    """Return the conventional WSL mount path for Windows drive text.

    :param path: Windows drive path text.
    :return: POSIX path under ``/mnt/<drive>``.
    """
    drive = path[0].lower()
    rest = path[2:].lstrip("\\/").replace("\\", "/")
    return Path(f"/mnt/{drive}") / rest


def _is_windows_drive_path(path: str) -> bool:
    """Return whether text starts with a Windows drive prefix.

    :param path: User-provided path text.
    :return: Whether the path begins with a Windows drive marker.
    """
    return bool(_WINDOWS_DRIVE_PATH_PATTERN.match(path))


def _is_malformed_windows_drive_path(path: str) -> bool:
    """Return whether text looks like a shell-damaged Windows path.

    :param path: User-provided path text.
    :return: Whether the path has a drive prefix without a path separator.
    """
    return bool(_MALFORMED_WINDOWS_DRIVE_PATH_PATTERN.match(path))


def _malformed_windows_drive_path_message(path: str) -> str:
    """Return guidance for Windows paths damaged by POSIX shell parsing.

    :param path: User-provided workspace root text.
    :return: Explanation with accepted path examples.
    """
    return (
        "Workspace root looks like a Windows drive path, but it is missing "
        f"a slash after the drive letter: {path!r}. On POSIX shells, "
        "unquoted backslashes are consumed before the app sees the value, so "
        r"`C:\Projects\demo-workspace` can arrive as "
        "`C:Projectsdemo-workspace`. "
        "Quote the path or use forward slashes. Accepted forms include "
        r"`'C:\Projects\demo-workspace'`, "
        "`C:/Projects/demo-workspace`, and "
        "`/mnt/c/Projects/demo-workspace`. To create a literal POSIX "
        "relative directory with this name, prefix it with `./`."
    )
