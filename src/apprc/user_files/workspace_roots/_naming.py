"""Workspace name and default-path helpers."""

from __future__ import annotations

# == Standard Library ========================
import re
from pathlib import Path

_WORKSPACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def suggested_workspace_root(app_id: str) -> Path:
    """Return the conventional per-application workspace root."""
    return Path.home() / ".local" / "share" / app_id / "workspaces"


def suggested_workspace_name(app_id: str) -> str:
    """Return the conventional name for a first workspace."""
    del app_id
    return "default"


def validate_workspace_name(name: str) -> None:
    """Reject names that cannot be written as simple TOML keys."""
    if not _WORKSPACE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Workspace names may contain only letters, numbers, underscores, "
            "and hyphens; they must not include `/` or `\\`."
        )
