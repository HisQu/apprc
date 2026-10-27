"""Path, read, and write helpers for AppRC dotenv override files.

User and workspace dotenv files use the same validation and write
rules: values are checked against declared ``ConfigField`` metadata, known
keys are written in declaration order, and unknown keys are preserved after
known AppRC keys.
"""

from __future__ import annotations

# == Standard Library ========================
import json
from pathlib import Path
from typing import Iterable, Mapping

from apprc.definition.env_config.lookup import iter_config_fields
from apprc.definition.env_config.schema import ConfigOwner

# == Internal ================================
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    assert_no_links,
    ensure_text_file,
    write_text_atomic,
)
from apprc.user_files.env_files._parsing import parse_dotenv_file
from apprc.user_files.workspace_roots.paths import (
    WorkspaceRootPathError,
    resolve_workspace_root_path,
)


def workspace_dotenv_path(
    workspace_root: Path,
    filename: str = "apprc.workspace.env",
) -> Path:
    """Return the dotenv override path owned by one workspace root.

    :param workspace_root: Workspace root that owns the dotenv file.
    :param filename: Dotenv filename inside the workspace root.
    :return: Absolute workspace dotenv path.
    """
    return (
        resolve_workspace_root_path(workspace_root, base=Path.cwd()) / filename
    )


def ensure_workspace_dotenv_file(
    workspace_root: Path,
    filename: str = "apprc.workspace.env",
) -> Path:
    """Create the workspace dotenv file when it is missing.

    :param workspace_root: Existing directory that owns the dotenv file.
    :param filename: Dotenv filename inside the workspace root.
    :return: Path to the existing dotenv file.
    :raises WorkspaceRootPathError: If the root is missing or not a directory.
    """
    root = require_existing_workspace_root(workspace_root)
    try:
        return ensure_text_file(root / filename)
    except AppRCDirectoryError as exc:
        raise WorkspaceRootPathError(str(exc)) from exc


def ensure_env_file(path: Path) -> Path:
    """Create an AppRC dotenv override file when it is missing.

    :param path: Dotenv path to create.
    :return: Path to the existing dotenv file.
    """
    return ensure_text_file(path)


def read_env_file(path: Path | None) -> dict[str, str]:
    """Parse an optional AppRC dotenv file into string key/value pairs.

    :param path: Dotenv file path, or ``None`` for an inactive layer.
    :return: Parsed string values. Missing files return an empty mapping.
    """
    return parse_dotenv_file(path)


def write_env_file(
    path: Path,
    values: Mapping[str, str],
    *,
    owners: Iterable[ConfigOwner],
) -> Path:
    """Write deterministic AppRC dotenv values.

    :param path: Dotenv file path to replace.
    :param values: Env values keyed by concrete environment variable.
    :param owners: Config owners that define known AppRC env keys.
    :return: Written dotenv path.
    """
    env_path = Path(path).expanduser()
    ordered_keys = _ordered_env_keys(owners)
    known_key_set = set(ordered_keys)
    known = [key for key in ordered_keys if key in values]
    unknown = sorted(key for key in values if key not in known_key_set)
    lines = [
        f"{key}={_dotenv_quote(values[key])}" for key in (*known, *unknown)
    ]
    return write_text_atomic(env_path, "\n".join(lines).rstrip() + "\n")


def require_existing_workspace_root(workspace_root: Path) -> Path:
    """Return a workspace root after proving it exists and is link-free.

    :param workspace_root: Root expected to own a workspace dotenv file.
    :return: Absolute existing workspace root.
    :raises WorkspaceRootPathError: If the root is missing or not a directory.
    """
    root = resolve_workspace_root_path(workspace_root, base=Path.cwd())
    assert_no_links(root)
    if not root.exists():
        raise WorkspaceRootPathError(f"Workspace root does not exist: {root!s}")
    if not root.is_dir():
        raise WorkspaceRootPathError(
            f"Workspace root is not a directory: {root!s}"
        )
    return root


def _ordered_env_keys(owners: Iterable[ConfigOwner]) -> tuple[str, ...]:
    """Return known env keys in owner declaration order."""
    return tuple(
        owner.env_key(spec.name) for owner, spec in iter_config_fields(owners)
    )


def _dotenv_quote(value: str) -> str:
    """Quote one value for deterministic dotenv output."""
    return json.dumps(value)
