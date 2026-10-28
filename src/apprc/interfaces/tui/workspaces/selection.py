"""Explicit workspace selection states for the config editor."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == Internal ================================
from apprc.user_files.workspace_roots.registry import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
)


@dataclass(frozen=True, slots=True)
class NoWorkspaceSelection:
    """State used when the editor has no workspace target."""

    kind: Literal["none"] = "none"


@dataclass(frozen=True, slots=True)
class ActivePathWorkspaceSelection:
    """Env-selected workspace root that is not backed by a named row."""

    root: Path
    kind: Literal["active_path"] = "active_path"


@dataclass(frozen=True, slots=True)
class LiveWorkspaceSelection:
    """Registry row whose workspace root can be edited."""

    record: WorkspaceRecord
    kind: Literal["live"] = "live"


@dataclass(frozen=True, slots=True)
class MissingWorkspaceSelection:
    """Registry row whose workspace root is missing or unusable."""

    record: WorkspaceRecord
    kind: Literal["missing"] = "missing"


@dataclass(frozen=True, slots=True)
class ArchivedWorkspaceSelection:
    """Archive convenience row selected from the workspace list."""

    record: ArchivedWorkspaceRecord
    kind: Literal["archived"] = "archived"


EditorWorkspaceSelection = (
    NoWorkspaceSelection
    | ActivePathWorkspaceSelection
    | LiveWorkspaceSelection
    | MissingWorkspaceSelection
    | ArchivedWorkspaceSelection
)
