"""Path helpers for AppRC contract-level files."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path


def normalize_apprc_toml_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded AppRC TOML path.

    :param path: User-provided TOML path.
    :return: Absolute path spelling.
    """
    return Path(path).expanduser().resolve()
