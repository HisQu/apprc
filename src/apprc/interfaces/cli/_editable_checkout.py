"""Identify the installed entry point and editable checkout using PEP 610 metadata."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname


def _distribution_name(name: str) -> str:
    """Normalize installed distribution names without optional authoring packages."""
    return re.sub(r"[-_.]+", "-", name).lower()


def editable_entry_point(
    command: str, expected_distribution: str | None = None
) -> tuple[
    importlib.metadata.EntryPoint, importlib.metadata.Distribution, Path
]:
    """Resolve the mounted command's editable distribution and file URL.

    :param command: Mounted console script name.
    :param expected_distribution: Normalized distribution name when known.
    :return: Installed entry point, its owning distribution and source path.
    """
    installed_commands = tuple(
        importlib.metadata.entry_points(
            group="console_scripts",
            name=command,
        )
    )
    if expected_distribution is not None:
        installed_commands = tuple(
            entry
            for entry in installed_commands
            if entry.dist is not None
            and _distribution_name(entry.dist.metadata["Name"])
            == expected_distribution
        )
    if len(installed_commands) != 1:
        raise ValueError(
            "The mounted console command does not identify one installed "
            "distribution."
        )
    installed_command = installed_commands[0]
    distribution = installed_command.dist
    if distribution is None:
        raise ValueError(
            "The mounted console command has no distribution owner."
        )
    direct_url = distribution.read_text("direct_url.json")
    direct = json.loads(direct_url) if direct_url is not None else None
    source_root = (
        _editable_source_path(direct["url"])
        if isinstance(direct, dict) and isinstance(direct.get("url"), str)
        else None
    )
    if (
        source_root is None
        or not isinstance(direct, dict)
        or not isinstance(direct.get("dir_info"), dict)
        or direct["dir_info"].get("editable") is not True
    ):
        raise ValueError("The installed distribution is not editable.")
    return installed_command, distribution, source_root


def _editable_source_path(url: str) -> Path:
    """Decode an editable file URL without dropping a network authority.

    :param url: Installed distribution's direct source URL.
    :return: Absolute source path in the current platform's filesystem.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.query or parsed.fragment:
        raise ValueError(
            "Editable source must be a file URL without query or fragment."
        )
    path = parsed.path
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        if os.name != "nt":
            raise ValueError(
                f"Cannot convert editable source URL {url!r} to a local "
                "filesystem path on this platform. Use the network share's "
                "mounted local path."
            )
        path = f"//{parsed.netloc}{path}"
    try:
        source = Path(url2pathname(path))
    except OSError as exc:
        raise ValueError(
            f"Cannot convert editable source URL {url!r} to a filesystem path: {exc}"
        ) from exc
    if not source.is_absolute():
        raise ValueError(
            "Editable source file URL must identify an absolute path."
        )
    return source
