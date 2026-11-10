"""Shared state and action results for config editor workspace workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorScreen
    from apprc.services.workspaces import WorkspaceManager


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


class WorkspaceWorkflowBase:
    """Store the editor and its workspace manager for TUI workflows.

    :param editor: Reusable config editor screen.
    """

    def __init__(self, editor: ConfigEditorScreen) -> None:
        """Capture the editor screen's explicitly configured workspace manager."""
        self.editor = editor

    def require_workspace_manager(self) -> WorkspaceManager:
        """Return workspace services or reject unavailable workspace controls.

        :return: The editor's explicitly configured workspace manager.
        :raises ValueError: If this editor has no workspace capability.
        """
        manager = self.editor.workspace_manager
        if manager is None:
            raise ValueError("Workspace controls require a WorkspaceManager.")
        return manager
