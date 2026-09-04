"""Storage name and default-path helpers."""

from __future__ import annotations

# == Standard Library ========================
import re
from collections.abc import Mapping
from pathlib import Path

# == Internal ===================================================
from apprc.user_files.app_home.locations import default_apprc_dir

_STORAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def app_data_dir(
    app_id: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user data directory for one application.

    :param app_id: Directory name below ``$XDG_DATA_HOME`` or
        ``~/.local/share``.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: ``$XDG_DATA_HOME/<app_id>`` or ``~/.local/share/<app_id>``.
    """
    del proc_env
    return default_apprc_dir(app_id)


def suggested_storage_root(
    app_id: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the conventional active storage root for a fresh setup."""
    return app_data_dir(app_id, proc_env) / "storage"


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
