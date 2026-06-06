"""Path normalization helpers for AppRC-owned storage roots."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def normalize_storage_root_path(path: str | Path) -> Path:
    """Return a platform-readable storage root path.

    AppRC registries may be initialized from Windows path text while running
    under WSL. This helper translates drive paths before normal ``Path``
    expansion so registry writes and env bootstrap use the same local spelling.

    :param path: User-provided storage root path.
    :return: Expanded local path without requiring the directory to exist.
    """
    path_text = str(path).strip()
    if _is_windows_drive_path(path_text):
        return windows_drive_path_to_posix(path_text).expanduser()
    return Path(path_text).expanduser()


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
            pass
        else:
            converted = result.stdout.strip()
            if converted:
                return Path(converted)

    drive = path[0].lower()
    rest = path[2:].lstrip("\\/").replace("\\", "/")
    return Path(f"/mnt/{drive}") / rest


def _is_windows_drive_path(path: str) -> bool:
    """Return whether text starts with a Windows drive prefix.

    :param path: User-provided path text.
    :return: Whether the path begins with a Windows drive marker.
    """
    return bool(_WINDOWS_DRIVE_PATH_PATTERN.match(path))
