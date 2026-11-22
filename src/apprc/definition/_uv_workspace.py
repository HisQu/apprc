"""Read uv workspace patterns for editable and committed project discovery."""

from __future__ import annotations

import glob
from pathlib import Path, PurePosixPath, PureWindowsPath


def workspace_patterns(
    workspace: object,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Validate relative patterns before opening either workspace route.

    :param workspace: Parsed ``tool.uv.workspace`` table.
    :return: Member and exclusion patterns in their declaration order.
    """
    if not isinstance(workspace, dict):
        raise ValueError("tool.uv.workspace must be a table.")
    members = _patterns(workspace.get("members", []), "members")
    excludes = _patterns(workspace.get("exclude", []), "excludes")
    for pattern in (*members, *excludes):
        path = PurePosixPath(pattern)
        if (
            not pattern
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in pattern
            or PureWindowsPath(pattern).drive
        ):
            raise ValueError(f"Unsafe uv workspace pattern: {pattern}.")
    return members, excludes


def _patterns(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"Workspace {label} must be relative path patterns.")
    return tuple(value)


def match_workspace_pattern(
    root: Path, pattern: str, *, include_hidden: bool
) -> set[Path]:
    """Expand a validated uv pattern from a literal workspace address.

    :param root: Directory containing the workspace declaration.
    :param pattern: Validated relative glob.
    :param include_hidden: Whether wildcards may match hidden entries.
    :return: Matches with their original spelling so callers can check links.
    """
    return {
        root / match
        for match in glob.glob(
            pattern,
            root_dir=root,
            recursive=True,
            include_hidden=include_hidden,
        )
    }
