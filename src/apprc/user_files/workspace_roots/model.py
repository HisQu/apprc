"""Workspace registry records used by AppRC multi-workspace mode."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    """One named workspace root from the workspace registry."""

    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class ArchivedWorkspaceRecord:
    """Last known archive for one workspace selector."""

    name: str
    archive: Path
    source_root: Path


@dataclass(frozen=True, slots=True)
class WorkspaceRegistry:
    """Parsed workspace registry."""

    path: Path
    workspaces: Mapping[str, WorkspaceRecord]
    selected_workspace: str | None = None
    archived_workspaces: Mapping[str, ArchivedWorkspaceRecord] = field(
        default_factory=dict
    )
    schema_version: int = 1

    def selected(self, name: str) -> WorkspaceRecord:
        """Return one named workspace or raise a readable error.

        :param name: Workspace selector requested by CLI or config.
        :return: Matching workspace record.
        :raises ValueError: If the workspace does not exist.
        """
        try:
            return self.workspaces[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.workspaces)) or "<none>"
            raise ValueError(
                f"Unknown workspace {name!r} in {self.path}. "
                f"Known workspaces: {known}."
            ) from exc
