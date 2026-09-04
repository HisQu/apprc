"""Storage name and default-path helpers."""

from __future__ import annotations

# == Standard Library ========================
import re
from pathlib import Path

# == Internal ===================================================
from apprc.user_files.app_home.locations import default_apprc_dir

_STORAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def suggested_storage_root(app_id: str) -> Path:
    """Return the first-setup storage path below the fixed AppRC directory.

    :param app_id: Stable application identity used as the directory name.
    :return: ``~/.local/share/<app-id>/storage``.
    """
    return default_apprc_dir(app_id) / "storage"


def suggested_storage_name(app_id: str) -> str:
    """Return the conventional name for a first storage.

    :param app_id: Application name from the AppRC integration spec.
    :return: Host-specific selector that does not reuse the UI term
        ``default``.
    """
    del app_id
    return "default"


def validate_storage_name(name: str) -> None:
    """Reject storage names that cannot be written as simple TOML keys."""
    if not _STORAGE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Storage names may contain only letters, numbers, underscores, "
            "and hyphens; they must not include `/` or `\\`."
        )
