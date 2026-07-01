"""Storage name and default-path helpers."""

from __future__ import annotations

# == Standard Library ========================
import os
import re
from collections.abc import Mapping
from pathlib import Path

_STORAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def app_data_dir(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user data directory for one application.

    :param app_name: Directory name below ``$XDG_DATA_HOME`` or
        ``~/.local/share``.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: ``$XDG_DATA_HOME/<app_name>`` or ``~/.local/share/<app_name>``.
    """
    env = os.environ if proc_env is None else proc_env
    xdg_data_home = env.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / app_name
    return Path.home() / ".local" / "share" / app_name


def suggested_storage_root(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the conventional active storage root for a fresh setup."""
    return app_data_dir(app_name, proc_env) / suggested_storage_name(app_name)


def suggested_storage_name(app_name: str) -> str:
    """Return the conventional name for a first storage.

    :param app_name: Application name from the AppRC integration spec.
    :return: Host-specific selector that does not reuse the UI term
        ``default``.
    """
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
    base_name = normalized or "apprc"
    return f"{base_name}_stor-1"


def validate_storage_name(name: str) -> None:
    """Reject storage names that cannot be written as simple TOML keys."""
    if not _STORAGE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Storage names may contain only letters, numbers, underscores, "
            "and hyphens; they must not include `/` or `\\`. Use "
            "<APP>_STORAGE or --storage-root for path values."
        )
