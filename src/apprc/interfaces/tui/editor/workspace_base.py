"""Workspace action inputs and presentation results for the config editor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import App

from apprc.interfaces.tui.workspaces import (
    EditorWorkspaceSelection,
    suggest_workspace_name,
)
from apprc.services.manager import ConfigManager
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.workspace_roots.model import WorkspaceRegistry


@dataclass(frozen=True, slots=True)
class WorkspaceActionResult:
    """Describe the presentation selection after a completed workspace action.

    ``None`` from a workflow means cancellation or failure and preserves the
    current selection. A result with ``use_fallback`` requests the normal
    active-workspace/registry fallback. ``active_root`` adopts a successfully
    initialized direct workspace root; ``select_name`` selects a named row.
    """

    select_name: str | None = None
    active_root: Path | None = None
    use_fallback: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceActionContext:
    """Fresh read-only inputs and UI host for one workspace action."""

    app: App[None]
    manager: ConfigManager
    workspace_manager: WorkspaceManager | None
    registry: WorkspaceRegistry | None
    registry_error: str | None
    selection: EditorWorkspaceSelection
    active_workspace_root: Path | None
    workspace_enabled: bool
    registry_enabled: bool
    user_dotenv_enabled: bool
    user_dotenv_active: bool


class WorkspaceWorkflowBase:
    """Provide shared workspace domain access for one immutable action context."""

    def __init__(self, context: WorkspaceActionContext) -> None:
        """Store the action's fresh service and presentation snapshot."""
        self.context = context

    def require_workspace_manager(self) -> WorkspaceManager:
        """Return workspace services or reject unavailable workspace controls."""
        manager = self.context.workspace_manager
        if manager is None:
            raise ValueError("Workspace controls require a WorkspaceManager.")
        return manager

    def require_workspace_registry(self) -> WorkspaceRegistry | None:
        """Return captured registry metadata or explain unavailable controls."""
        if self.context.registry is None:
            self.context.app.notify(
                self.context.registry_error
                or "This workspace declaration does not use a registry.",
                severity="error",
                markup=False,
            )
        return self.context.registry

    def suggest_workspace_name(self, path: Path) -> str:
        """Suggest a selector using the declared app identifier as fallback."""
        return suggest_workspace_name(
            path,
            fallback_name=self.context.manager.schema.app_id,
        )
